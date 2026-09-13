import {useEffect,useMemo,useState} from 'react';
import {getPerformance} from '../api/client';
import {formatEasternDateTime} from '../lib/dates';
import type {PerformanceResponse,PerformanceSignal} from '../types';

type OutcomeUnit='R'|'PCT';
type PerformanceStrategy='ONE_MIN_0DTE'|'STRUCTURED_INTRADAY';
type LedgerView='ALL'|'OPEN'|'COMPLETED'|'EXCLUDED';

const labels:Record<string,string>={
  total_triggered_signals:'Selected positions',resolved_signals:'Resolved',wins:'Wins',losses:'Losses',
  win_rate:'Win rate %',profit_factor:'Profit factor',exposure_ticker_days:'Ticker-days exposed',
  quality_exclusions:'Quality exclusions',average_duration:'Avg duration min',
};

function visibleInView(row:PerformanceSignal,view:LedgerView):boolean{
  if(view==='OPEN')return row.exit_reason==='OPEN';
  if(view==='COMPLETED')return row.exit_reason!=='OPEN';
  if(view==='EXCLUDED')return !row.analytics_eligible;
  return true;
}

function metricsFor(rows:PerformanceSignal[],unit:OutcomeUnit):Record<string,number|null>{
  const ordered=[...rows].sort((a,b)=>a.triggered_at.localeCompare(b.triggered_at));
  const completed=ordered.filter(row=>row.analytics_eligible&&row.exit_reason!=='OPEN'&&
    (unit==='R'?row.result_r:row.result_return_pct)!==null);
  const values=completed.map(row=>(unit==='R'?row.result_r:row.result_return_pct) as number);
  const wins=values.filter(value=>value>0),losses=values.filter(value=>value<0);
  let equity=0,peak=0,drawdown=0;
  for(const value of values){equity+=value;peak=Math.max(peak,equity);drawdown=Math.max(drawdown,peak-equity)}
  return {
    total_triggered_signals:rows.length,resolved_signals:completed.length,wins:wins.length,losses:losses.length,
    win_rate:completed.length?Number((100*wins.length/completed.length).toFixed(1)):0,
    average_outcome:values.length?Number((values.reduce((sum,value)=>sum+value,0)/values.length).toFixed(3)):0,
    cumulative_outcome:Number(values.reduce((sum,value)=>sum+value,0).toFixed(3)),
    profit_factor:losses.length?Number((wins.reduce((sum,value)=>sum+value,0)/Math.abs(losses.reduce((sum,value)=>sum+value,0))).toFixed(2)):null,
    maximum_drawdown:Number(drawdown.toFixed(3)),
    average_win:wins.length?Number((wins.reduce((sum,value)=>sum+value,0)/wins.length).toFixed(3)):0,
    average_loss:losses.length?Number((losses.reduce((sum,value)=>sum+value,0)/losses.length).toFixed(3)):0,
    exposure_ticker_days:new Set(rows.map(row=>`${row.trading_date}:${row.ticker}`)).size,
    quality_exclusions:rows.filter(row=>!row.analytics_eligible).length,
    average_duration:completed.length?Number((completed.reduce((sum,row)=>sum+(row.duration_minutes??0),0)/completed.length).toFixed(1)):0,
  };
}

const strategyName=(mode:PerformanceStrategy)=>mode==='STRUCTURED_INTRADAY'?'Structured Intraday · 5–14 DTE':'1-Min · true 0DTE';
const validResponse=(value:PerformanceResponse)=>Array.isArray(value?.signals)&&Boolean(value?.metrics)&&Boolean(value?.raw_metrics);

export function Performance(){
  const [datasets,setDatasets]=useState<Record<PerformanceStrategy,PerformanceResponse>|null>(null);
  const [view,setView]=useState<LedgerView>('ALL');
  const [strategy,setStrategy]=useState<PerformanceStrategy>('ONE_MIN_0DTE');
  const [unit,setUnit]=useState<OutcomeUnit>('R');
  const [expanded,setExpanded]=useState('');
  useEffect(()=>{void Promise.all([getPerformance('ONE_MIN_0DTE'),getPerformance('STRUCTURED_INTRADAY')])
    .then(([zeroDte,structured])=>{if(validResponse(zeroDte)&&validResponse(structured))setDatasets({ONE_MIN_0DTE:zeroDte,STRUCTURED_INTRADAY:structured})})},[]);
  const data=datasets?.[strategy]??null;
  const rows=useMemo(()=>data?.signals.filter(row=>visibleInView(row,view))??[],[data,view]);
  const selectedMetrics=useMemo(()=>metricsFor(rows,unit),[rows,unit]);
  const suffix=unit==='R'?'R':'%';
  const metricLabels:Record<string,string>={...labels,average_outcome:`Average ${unit==='R'?'R':'underlying return %'}`,
    cumulative_outcome:`Cumulative ${unit==='R'?'R':'underlying return %'}`,maximum_drawdown:`Max drawdown ${suffix}`,
    average_win:`Avg win ${suffix}`,average_loss:`Avg loss ${suffix}`};
  return <section id="performance" className="performance-page">
    <p className="eyebrow">Automated research · one position per ticker/day</p><h2>Performance</h2>
    <p><strong>Underlying-path research only—not option-contract P/L.</strong> Manual positions and backtests are excluded. The first actual BUY per ticker/day is retained; cross-session and zero-risk outcomes stay visible but do not enter results.</p>
    <div className="performance-controls"><div><span>Strategy (kept separate)</span><div className="filter-tabs">
      {([['ONE_MIN_0DTE','True 0DTE'],['STRUCTURED_INTRADAY','Structured 5–14 DTE']] as [PerformanceStrategy,string][]).map(([value,label])=><button className={strategy===value?'active':''} onClick={()=>{setStrategy(value);setView('ALL')}} key={value}>{label}</button>)}
    </div></div><div><span>Outcome</span><div className="filter-tabs"><button className={unit==='R'?'active':''} onClick={()=>setUnit('R')}>R Multiple</button><button className={unit==='PCT'?'active':''} onClick={()=>setUnit('PCT')}>Underlying %</button></div></div></div>
    <div className="filter-tabs source-tabs">{(['ALL','OPEN','COMPLETED','EXCLUDED'] as LedgerView[]).map(value=><button className={view===value?'active':''} onClick={()=>setView(value)} key={value}>{value}</button>)}</div>
    {data&&<><p><strong>{strategyName(strategy)}</strong> · {data.raw_metrics.total_triggered_signals} raw BUY rows → {data.metrics.total_triggered_signals} selected ticker-day positions. Raw eligible R: {data.raw_metrics.cumulative_r.toFixed(3)}R; selected eligible R: {data.metrics.cumulative_r.toFixed(3)}R.</p>
      <div className="option-shadow"><p><strong>Automated option shadow · forward only, not headline results</strong></p>
        <p>Entry uses the verified ask; exit uses the first verified bid after the underlying target, stop, or 15:45 ET cutoff. No midpoint, last-price, or underlying-price substitution. Fees and additional slippage are not yet modeled.</p>
        <div className="performance-metrics">
          <div className="metric"><span>Tracked</span><strong>{data.option_shadow_metrics.tracked_positions}</strong></div>
          <div className="metric"><span>Closed with quote</span><strong>{data.option_shadow_metrics.closed_with_quote}</strong></div>
          <div className="metric"><span>Quote gaps</span><strong>{data.option_shadow_metrics.quote_gaps}</strong></div>
          <div className="metric"><span>Coverage</span><strong>{data.option_shadow_metrics.quote_coverage_percent}%</strong></div>
          <div className="metric"><span>Shadow option P/L</span><strong>${data.option_shadow_metrics.cumulative_pnl_dollars.toFixed(2)}</strong></div>
          <div className="metric"><span>Avg option return</span><strong>{data.option_shadow_metrics.average_return_percent.toFixed(2)}%</strong></div>
        </div>
        {data.option_shadow_metrics.tracked_positions===0&&<p>No marks yet. Collection begins with the first automated BUY after this patch; old rows are intentionally not backfilled.</p>}
      </div>
      <div className="performance-metrics">{Object.entries(selectedMetrics).map(([key,value])=><div className="metric" key={key}><span>{metricLabels[key]}</span><strong>{value??'N/A'}</strong></div>)}</div>
      <div className="ledger" role="table"><div className="ledger-row ledger-head"><b>Ticker</b><b>Strategy / setup</b><b>Trigger (ET)</b><b>Plan</b><b>Outcome</b></div>{rows.map(row=>{const outcome=unit==='R'?row.result_r:row.result_return_pct;const excluded=row.analytics_exclusion_reason?` · EXCLUDED: ${row.analytics_exclusion_reason.replaceAll('_',' ')}`:'';return <div key={row.signal_id}><button className="ledger-row" onClick={()=>setExpanded(expanded===row.signal_id?'':row.signal_id)}><b>{row.ticker}</b><span>{strategyName(strategy)} · {row.direction} · {row.setup_type}</span><span>{formatEasternDateTime(row.triggered_at)}</span><span>{row.entry_price.toFixed(2)} / {row.stop_price.toFixed(2)} / {row.target_price.toFixed(2)}</span><span>{row.exit_reason} · {outcome==null?'—':`${outcome.toFixed(2)}${suffix}`}{excluded}</span></button>{expanded===row.signal_id&&<pre className="audit-view">{JSON.stringify({analytics_eligible:row.analytics_eligible,analytics_exclusion_reason:row.analytics_exclusion_reason,strategy_mode:row.strategy_mode,strategy_version:row.strategy_version,initial_risk_points:row.initial_risk_points,initial_risk_pct:row.initial_risk_pct,strategy:row.strategy_snapshot,conditions:row.condition_snapshot,option_at_trigger:row.option_snapshot,automated_option_shadow:row.automated_option_shadow,conservative_same_candle:row.conservative_same_candle},null,2)}</pre>}</div>})}</div></>}
  </section>;
}
