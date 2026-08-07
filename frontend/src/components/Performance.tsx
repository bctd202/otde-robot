import {useEffect,useMemo,useState} from 'react';
import {getPerformance} from '../api/client';
import {formatEasternDateTime} from '../lib/dates';
import type {PerformanceResponse,PerformanceSignal,StrategyView} from '../types';

type OutcomeUnit='R'|'PCT';
const baseLabels:Record<string,string>={total_triggered_signals:'Triggered',open_signals:'Open',targets_hit:'Targets',stops_hit:'Stops',timed_exits:'Timed exits',invalidated_missed:'Invalid / missed',win_rate:'Win rate %',profit_factor:'Profit factor',average_duration:'Avg duration min'};

function visibleInView(row:PerformanceSignal,view:string):boolean{if(view==='ALL')return true;if(view==='PAPER')return row.user_entered;if(view==='LIVE')return row.source==='LIVE';if(view==='BACKTEST')return row.source==='BACKTEST';if(view==='OPEN')return row.exit_reason==='OPEN';if(view==='AUDIT')return ['UNKNOWN','LEGACY'].includes(row.source);return row.exit_reason!=='OPEN'}
function inStrategy(row:PerformanceSignal,strategy:StrategyView):boolean{return strategy==='ALL'||row.strategy_mode===strategy}

function metricsFor(rows:PerformanceSignal[],unit:OutcomeUnit):Record<string,number|null>{
  const completed=rows.filter(row=>row.exit_reason!=='OPEN'&&(unit==='R'?row.result_r:row.result_return_pct)!==null);
  const values=completed.map(row=>(unit==='R'?row.result_r:row.result_return_pct) as number);
  const mfe=completed.map(row=>unit==='R'?row.mfe_r:row.mfe_return_pct);
  const mae=completed.map(row=>unit==='R'?row.mae_r:row.mae_return_pct);
  const wins=values.filter(value=>value>0),losses=values.filter(value=>value<0);
  let equity=0,peak=0,drawdown=0;for(const value of values){equity+=value;peak=Math.max(peak,equity);drawdown=Math.max(drawdown,peak-equity)}
  return {total_triggered_signals:rows.length,open_signals:rows.filter(row=>row.exit_reason==='OPEN').length,targets_hit:rows.filter(row=>row.exit_reason==='TARGET').length,stops_hit:rows.filter(row=>row.exit_reason==='STOP').length,timed_exits:rows.filter(row=>row.exit_reason==='TIMED_EXIT').length,invalidated_missed:rows.filter(row=>['INVALIDATED','MISSED'].includes(row.exit_reason)).length,win_rate:completed.length?Number((100*wins.length/completed.length).toFixed(1)):0,average_outcome:values.length?Number((values.reduce((sum,value)=>sum+value,0)/values.length).toFixed(3)):0,cumulative_outcome:Number(values.reduce((sum,value)=>sum+value,0).toFixed(3)),profit_factor:losses.length?Number((wins.reduce((sum,value)=>sum+value,0)/Math.abs(losses.reduce((sum,value)=>sum+value,0))).toFixed(2)):null,maximum_drawdown:Number(drawdown.toFixed(3)),average_duration:completed.length?Number((completed.reduce((sum,row)=>sum+(row.duration_minutes??0),0)/completed.length).toFixed(1)):0,average_mfe:mfe.length?Number((mfe.reduce((sum,value)=>sum+value,0)/mfe.length).toFixed(3)):0,average_mae:mae.length?Number((mae.reduce((sum,value)=>sum+value,0)/mae.length).toFixed(3)):0};
}

const strategyName=(mode:string)=>mode==='STRUCTURED_INTRADAY'?'Structured Intraday':'1-Min / 0DTE';

export function Performance(){
  const [data,setData]=useState<PerformanceResponse|null>(null);
  const [view,setView]=useState('ALL');
  const [strategy,setStrategy]=useState<StrategyView>('ALL');
  const [unit,setUnit]=useState<OutcomeUnit>('PCT');
  const [expanded,setExpanded]=useState('');
  useEffect(()=>{void getPerformance().then(value=>{if(value&&Array.isArray(value.signals)&&value.metrics)setData(value)})},[]);
  const rows=useMemo(()=>data?.signals.filter(row=>visibleInView(row,view)&&inStrategy(row,strategy))??[],[data,view,strategy]);
  const selectedMetrics=useMemo(()=>metricsFor(rows,unit),[rows,unit]);
  const suffix=unit==='R'?'R':'%';
  const labels:Record<string,string>={...baseLabels,average_outcome:`Average ${unit==='R'?'R':'return %'}`,cumulative_outcome:`Cumulative ${unit==='R'?'R':'return %'}`,maximum_drawdown:`Max drawdown ${suffix}`,average_mfe:`Avg MFE ${suffix}`,average_mae:`Avg MAE ${suffix}`};
  return <section id="performance" className="performance-page"><p className="eyebrow">Normalized strategy evaluation</p><h2>Performance</h2><p>R uses the original underlying stop distance. Return % uses the actual option result for closed paper trades and the underlying result otherwise.</p>
    <div className="performance-controls"><div><span>Strategy</span><div className="filter-tabs">{([['ALL','All'],['ONE_MIN_0DTE','1-Min'],['STRUCTURED_INTRADAY','Structured']] as [StrategyView,string][]).map(([value,label])=><button className={strategy===value?'active':''} onClick={()=>setStrategy(value)} key={value}>{label}</button>)}</div></div><div><span>Outcome</span><div className="filter-tabs"><button className={unit==='PCT'?'active':''} onClick={()=>setUnit('PCT')}>Return %</button><button className={unit==='R'?'active':''} onClick={()=>setUnit('R')}>R Multiple</button></div></div></div>
    <div className="filter-tabs source-tabs">{['ALL','LIVE','PAPER','BACKTEST','OPEN','COMPLETED','AUDIT'].map(value=><button className={view===value?'active':''} onClick={()=>setView(value)} key={value}>{value}</button>)}</div>
    {data&&<><div className="performance-metrics">{Object.entries(selectedMetrics).map(([key,value])=><div className="metric" key={key}><span>{labels[key]}</span><strong>{value??'N/A'}</strong></div>)}</div><div className="ledger" role="table"><div className="ledger-row ledger-head"><b>Ticker</b><b>Strategy / setup</b><b>Trigger (ET)</b><b>Plan</b><b>Outcome</b></div>{rows.map(row=>{const outcome=unit==='R'?row.result_r:row.result_return_pct;const basis=unit==='PCT'&&row.return_basis==='PAPER_OPTION'?' · OPTION':'';return <div key={row.signal_id}><button className="ledger-row" onClick={()=>setExpanded(expanded===row.signal_id?'':row.signal_id)}><b>{row.ticker}</b><span>{strategyName(row.strategy_mode)} · {row.direction} · {row.setup_type}</span><span>{formatEasternDateTime(row.triggered_at)}</span><span>{row.entry_price.toFixed(2)} / {row.stop_price.toFixed(2)} / {row.target_price.toFixed(2)}</span><span>{row.exit_reason} · {outcome==null?'—':`${outcome.toFixed(2)}${suffix}`}{row.user_entered?' · PAPER':''}{basis}</span></button>{expanded===row.signal_id&&<pre className="audit-view">{JSON.stringify({strategy_mode:row.strategy_mode,strategy_version:row.strategy_version,initial_risk_points:row.initial_risk_points,initial_risk_pct:row.initial_risk_pct,return_basis:row.return_basis,paper_entry_option_price:row.paper_entry_option_price,paper_exit_option_price:row.paper_exit_option_price,strategy:row.strategy_snapshot,conditions:row.condition_snapshot,option_at_trigger:row.option_snapshot,conservative_same_candle:row.conservative_same_candle},null,2)}</pre>}</div>})}</div></>}
  </section>;
}
