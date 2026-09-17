import {useEffect,useMemo,useState} from 'react';
import {getPerformance} from '../api/client';
import {formatEasternDateTime} from '../lib/dates';
import type {PerformanceDailyPoint,PerformanceResponse,PerformanceSignal} from '../types';

type OutcomeUnit='R'|'DIRECTIONAL'|'RAW';
type PerformanceStrategy='ONE_MIN_0DTE'|'STRUCTURED_INTRADAY';
type LedgerView='ALL'|'OPEN'|'COMPLETED'|'EXCLUDED';
type GraphPoint={trading_date:string;daily_value:number;cumulative_value:number;resolved:number};

const PAGE_SIZES=[10,25,50];
const dollars=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'});
const strategyName=(mode:PerformanceStrategy)=>mode==='STRUCTURED_INTRADAY'?'Structured Intraday · 5–14 DTE':'1-Min · true 0DTE';
const shortDate=(value:string)=>new Date(`${value}T12:00:00`).toLocaleDateString('en-US',{month:'short',day:'numeric'});
const humanize=(value:string)=>value.replaceAll('_',' ').replaceAll('-',' ');
const validResponse=(value:PerformanceResponse)=>Array.isArray(value?.signals)&&Array.isArray(value?.chart_data?.daily)&&Array.isArray(value?.market_movement?.daily)&&Boolean(value?.pagination)&&Boolean(value?.metrics);

function signed(value:number,digits=2,suffix=''):string{
  return `${value>0?'+':''}${value.toFixed(digits)}${suffix}`;
}

function graphPoints(data:PerformanceResponse,unit:OutcomeUnit):GraphPoint[]{
  if(unit==='R')return data.chart_data.daily.map(point=>({trading_date:point.trading_date,daily_value:point.result_r,cumulative_value:point.cumulative_r,resolved:point.resolved}));
  return data.market_movement.daily.map(point=>({trading_date:point.trading_date,resolved:point.resolved,
    daily_value:unit==='DIRECTIONAL'?point.directional_move_pct:point.raw_move_pct,
    cumulative_value:unit==='DIRECTIONAL'?point.cumulative_directional_move_pct:point.cumulative_raw_move_pct}));
}

function playMove(row:PerformanceSignal,unit:OutcomeUnit):number|null{
  if(unit==='R')return row.result_r;
  if(row.exit_price==null||row.entry_price<=0)return null;
  const raw=(row.exit_price-row.entry_price)/row.entry_price*100;
  return unit==='DIRECTIONAL'&&row.direction==='PUT'?-raw:raw;
}

function EmptyGraph({children}:{children:string}){
  return <div className="graph-empty"><span>Graph begins with qualified results</span><p>{children}</p></div>;
}

function CumulativeChart({points,unit}:{points:GraphPoint[];unit:OutcomeUnit}){
  if(points.length===0)return <EmptyGraph>{unit==='R'?'No completed, analytics-eligible plays are available yet.':'No eligible resolved plays with saved entry and exit prices are available yet.'}</EmptyGraph>;
  const width=760,height=260,left=52,right=18,top=18,bottom=40;
  const values=points.map(point=>point.cumulative_value);
  let min=Math.min(0,...values),max=Math.max(0,...values);
  if(max===min){max+=1;min-=1}
  const x=(index:number)=>points.length===1?(left+width-right)/2:left+index*(width-left-right)/(points.length-1);
  const y=(value:number)=>top+(max-value)*(height-top-bottom)/(max-min);
  const line=values.map((value,index)=>`${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(' ');
  const zeroY=y(0);
  const fill=`${left},${zeroY} ${line} ${x(points.length-1)},${zeroY}`;
  const axisDigits=max-min<8?1:0;
  const label=unit==='R'?'Strategy R':unit==='DIRECTIONAL'?'directional underlying move':'raw underlying move';
  return <svg className="performance-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Cumulative ${label} by trading day`}>
    {[0,.25,.5,.75,1].map(level=>{const value=min+(max-min)*level;const lineY=y(value);return <g key={level}><line className="graph-grid" x1={left} x2={width-right} y1={lineY} y2={lineY}/><text className="graph-axis" x={left-7} y={lineY+4} textAnchor="end">{value.toFixed(axisDigits)}{unit==='R'?'R':'%'}</text></g>})}
    <line className="graph-zero" x1={left} x2={width-right} y1={zeroY} y2={zeroY}/>
    <polygon className="graph-area" points={fill}/><polyline className="graph-line" points={line}/>
    {points.map((point,index)=><circle className="graph-point" key={point.trading_date} cx={x(index)} cy={y(values[index])} r="4"><title>{`${shortDate(point.trading_date)} · ${signed(values[index],2,unit==='R'?'R':'%')}`}</title></circle>)}
    <text className="graph-axis" x={left} y={height-13}>{shortDate(points[0].trading_date)}</text>
    <text className="graph-axis" x={width-right} y={height-13} textAnchor="end">{shortDate(points[points.length-1].trading_date)}</text>
  </svg>;
}

function DailyBars({points,unit}:{points:GraphPoint[];unit:OutcomeUnit}){
  const visible=points.slice(-30);
  if(visible.length===0)return <EmptyGraph>{unit==='R'?'Daily bars appear after the first resolved play.':'Daily bars appear after the first priced, resolved play.'}</EmptyGraph>;
  const width=620,height=250,left=45,right=14,top=16,bottom=38;
  const values=visible.map(point=>point.daily_value);
  const extent=Math.max(1,Math.abs(Math.min(0,...values)),Math.abs(Math.max(0,...values)));
  const y=(value:number)=>top+(extent-value)*(height-top-bottom)/(extent*2);
  const zeroY=y(0),slot=(width-left-right)/visible.length,barWidth=Math.min(48,Math.max(4,slot*.62));
  const every=Math.max(1,Math.ceil(visible.length/6));
  const label=unit==='R'?'Strategy R':unit==='DIRECTIONAL'?'directional underlying move':'raw underlying move';
  return <svg className="performance-bar-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Daily ${label} results`}>
    <line className="graph-zero" x1={left} x2={width-right} y1={zeroY} y2={zeroY}/>
    {visible.map((point,index)=>{const value=values[index],barY=value>=0?y(value):zeroY,barHeight=Math.max(1,Math.abs(y(value)-zeroY));return <g key={point.trading_date}><rect className={value>=0?'daily-bar positive':'daily-bar negative'} x={left+index*slot+(slot-barWidth)/2} y={barY} width={barWidth} height={barHeight} rx="2"><title>{`${shortDate(point.trading_date)} · ${signed(value,2,unit==='R'?'R':'%')} · ${point.resolved} resolved`}</title></rect>{index%every===0&&<text className="graph-axis" x={left+index*slot+slot/2} y={height-14} textAnchor="middle">{shortDate(point.trading_date)}</text>}</g>})}
  </svg>;
}

function OutcomeGraph({data}:{data:PerformanceResponse['chart_data']['outcomes']}){
  if(data.length===0)return <EmptyGraph>Outcome counts will appear once plays enter the ledger.</EmptyGraph>;
  const total=data.reduce((sum,item)=>sum+item.count,0);
  return <div className="outcome-graph" role="img" aria-label="Play outcome distribution">
    <div className="outcome-stack">{data.map(item=><span className={`outcome-segment outcome-${item.outcome.toLowerCase()}`} style={{width:`${100*item.count/total}%`}} key={item.outcome} title={`${item.outcome}: ${item.count}`}/>)}</div>
    <div className="outcome-legend">{data.map(item=><div key={item.outcome}><i className={`outcome-${item.outcome.toLowerCase()}`}/><span>{item.outcome.replaceAll('_',' ')}</span><strong>{item.count}</strong></div>)}</div>
  </div>;
}

function OptionEquityChart({points}:{points:PerformanceDailyPoint[]}){
  const optionPoints=points.filter(point=>point.option_closed>0);
  if(optionPoints.length===0)return <EmptyGraph>The ask-to-bid option curve begins with the first post-update automated exit.</EmptyGraph>;
  const width=620,height=250,left=52,right=18,top=18,bottom=40;
  const values=optionPoints.map(point=>point.cumulative_option_pnl_dollars);
  let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max){min-=10;max+=10}
  const x=(index:number)=>optionPoints.length===1?(left+width-right)/2:left+index*(width-left-right)/(optionPoints.length-1);
  const y=(value:number)=>top+(max-value)*(height-top-bottom)/(max-min);
  const line=values.map((value,index)=>`${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(' ');
  return <svg className="performance-line-chart option-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Cumulative automated option shadow profit and loss">
    <line className="graph-zero" x1={left} x2={width-right} y1={y(0)} y2={y(0)}/><polyline className="graph-line" points={line}/>
    {optionPoints.map((point,index)=><circle className="graph-point" key={point.trading_date} cx={x(index)} cy={y(values[index])} r="4"><title>{`${shortDate(point.trading_date)} · ${dollars.format(values[index])}`}</title></circle>)}
    <text className="graph-axis" x={left} y={height-13}>{shortDate(optionPoints[0].trading_date)}</text><text className="graph-axis" x={width-right} y={height-13} textAnchor="end">{shortDate(optionPoints[optionPoints.length-1].trading_date)}</text>
  </svg>;
}

function PlanRail({row}:{row:PerformanceSignal}){
  const markers=[{label:'Stop',value:row.stop_price,className:'stop'},{label:'Entry',value:row.entry_price,className:'entry'},{label:'Target',value:row.target_price,className:'target'},...(row.exit_price==null?[]:[{label:'Exit',value:row.exit_price,className:'exit'}])];
  let min=Math.min(...markers.map(marker=>marker.value)),max=Math.max(...markers.map(marker=>marker.value));
  const padding=Math.max((max-min)*.1,.01);min-=padding;max+=padding;
  const position=(value:number)=>`${Math.max(2,Math.min(98,100*(value-min)/(max-min)))}%`;
  return <div className="plan-rail" role="img" aria-label={`${row.ticker} price plan from stop through target`}><div className={`plan-track ${row.direction.toLowerCase()}`}/>{markers.map(marker=><span className={`plan-marker ${marker.className}`} style={{left:position(marker.value)}} key={marker.label}><i/><b>{marker.label}</b><small>{marker.value.toFixed(2)}</small></span>)}</div>;
}

function PlayCard({row,expanded,onToggle,unit}:{row:PerformanceSignal;expanded:boolean;onToggle:()=>void;unit:OutcomeUnit}){
  const shadow=row.automated_option_shadow;
  const underlying=playMove(row,unit);
  const suffix=unit==='R'?'R':'%';
  const resultLabel=unit==='R'?'Strategy R':unit==='DIRECTIONAL'?'Directional move':'Raw underlying move';
  const outcome=row.analytics_exclusion_reason?'EXCLUDED':row.exit_reason;
  const optionResult=shadow?.pnl_dollars;
  const optionClass=optionResult==null?'':optionResult>=0?'positive-text':'negative-text';
  return <article className={`performance-play-card play-${outcome.toLowerCase()}`}>
    <header><div><div className="play-tags"><span>{row.ticker} {row.direction}</span><small>{row.strategy_mode==='STRUCTURED_INTRADAY'?'STRUCTURED':'TRUE 0DTE'}</small></div><h3>{humanize(row.setup_type)}</h3><p>{formatEasternDateTime(row.triggered_at)} · score {row.score.toFixed(1)}</p></div><strong className="play-outcome">{humanize(outcome)}</strong></header>
    <div className="play-result-grid"><div><span>{resultLabel}</span><strong className={underlying==null?'':underlying>=0?'positive-text':'negative-text'}>{underlying==null?'—':signed(underlying,2,suffix)}</strong></div><div><span>Option shadow</span><strong className={optionClass}>{optionResult==null?(shadow?.status.replaceAll('_',' ')??'Not tracked'):`${optionResult>0?'+':''}${dollars.format(optionResult)}`}</strong><small>{optionResult==null?'Ask → bid evidence':`${dollars.format(shadow?.entry_cost_dollars??0)} → ${dollars.format(shadow?.exit_value_dollars??0)}`}</small></div><div><span>Time in play</span><strong>{row.duration_minutes==null?'Open':`${row.duration_minutes} min`}</strong></div><div><span>Excursion</span><strong>+{row.mfe_r.toFixed(2)}R / -{row.mae_r.toFixed(2)}R</strong><small>best / worst</small></div></div>
    <PlanRail row={row}/>
    {shadow&&<div className="option-journey"><span>OPTION EVIDENCE</span><strong>{shadow.option_symbol}</strong><p>Entry ask {dollars.format(shadow.entry_ask)}{shadow.exit_bid==null?' · awaiting or missing exit bid':` → exit bid ${dollars.format(shadow.exit_bid)}`}</p>{shadow.gap_reason&&<small>{shadow.gap_reason}</small>}</div>}
    <button className="play-detail-toggle" type="button" aria-expanded={expanded} onClick={onToggle}>{expanded?'Hide details':'See play details'}</button>
    {expanded&&<div className="play-details"><dl><div><dt>Triggered</dt><dd>{formatEasternDateTime(row.triggered_at)}</dd></div><div><dt>Exited</dt><dd>{formatEasternDateTime(row.exit_at)}</dd></div><div><dt>Entry / stop / target</dt><dd>{row.entry_price.toFixed(2)} / {row.stop_price.toFixed(2)} / {row.target_price.toFixed(2)}</dd></div><div><dt>Initial risk</dt><dd>{row.initial_risk_points.toFixed(2)} points · {row.initial_risk_pct.toFixed(2)}%</dd></div><div><dt>Eligible for stats</dt><dd>{row.analytics_eligible?'Yes':`No — ${row.analytics_exclusion_reason?.replaceAll('_',' ')}`}</dd></div><div><dt>Same-candle rule</dt><dd>{row.conservative_same_candle?'Conservative stop used':'Not invoked'}</dd></div></dl><details className="raw-audit"><summary>Technical audit data</summary><pre>{JSON.stringify({strategy_version:row.strategy_version,strategy:row.strategy_snapshot,conditions:row.condition_snapshot,option_at_trigger:row.option_snapshot,automated_option_shadow:row.automated_option_shadow},null,2)}</pre></details></div>}
  </article>;
}

export function Performance(){
  const [data,setData]=useState<PerformanceResponse|null>(null);
  const [view,setView]=useState<LedgerView>('ALL');
  const [strategy,setStrategy]=useState<PerformanceStrategy>('ONE_MIN_0DTE');
  const [unit,setUnit]=useState<OutcomeUnit>('R');
  const [page,setPage]=useState(1);
  const [pageSize,setPageSize]=useState(25);
  const [expanded,setExpanded]=useState('');
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  useEffect(()=>{let cancelled=false;setLoading(true);setError('');void getPerformance(strategy,{page,pageSize,view}).then(result=>{if(cancelled)return;if(!validResponse(result))throw new Error('Performance response was incomplete');setData(result);setPage(result.pagination.page)}).catch(reason=>{if(!cancelled)setError(reason instanceof Error?reason.message:'Unable to load performance')}).finally(()=>{if(!cancelled)setLoading(false)});return()=>{cancelled=true}},[strategy,view,page,pageSize]);
  const metrics=data?.metrics;
  const movement=data?.market_movement;
  const graphData=useMemo(()=>data?graphPoints(data,unit):[],[data,unit]);
  const metricCards=useMemo((): [string,string][]=>{
    if(!metrics||!movement)return [];
    if(unit==='R')return [
      ['Total R',signed(metrics.cumulative_r,2,'R')],
      ['Average R per resolved play',signed(metrics.average_r,3,'R')],
      ['Win Rate',`${metrics.win_rate}%`],
      ['Profit Factor',metrics.profit_factor?.toFixed(2)??'N/A'],
      ['Max Drawdown in R',`${metrics.maximum_drawdown_r.toFixed(2)}R`],
      ['Resolved Plays',metrics.resolved_signals.toString()],
      ['Open Plays',metrics.open_signals.toString()],
      ['Total Selected Plays',metrics.total_triggered_signals.toString()],
    ];
    if(unit==='DIRECTIONAL')return [
      ['Average Directional Move',signed(movement.average_directional_move_pct,3,'%')],
      ['Positive Direction Rate',`${movement.positive_direction_rate}%`],
      ['Cumulative Directional Move',signed(movement.cumulative_directional_move_pct,2,'%')],
      ['Resolved with prices',movement.resolved_with_prices.toString()],
    ];
    return [
      ['Net Raw Underlying Move',signed(movement.net_raw_underlying_move_pct,2,'%')],
      ['Avg. Raw Underlying Move',signed(movement.average_raw_underlying_move_pct,3,'%')],
      ['Resolved with prices',movement.resolved_with_prices.toString()],
    ];
  },[metrics,movement,unit]);
  const glanceCards=unit==='R'?metricCards.slice(0,4):metricCards.slice(0,3);
  const headline=unit==='R'?signed(metrics?.cumulative_r??0,2,'R'):unit==='DIRECTIONAL'?
    signed(movement?.cumulative_directional_move_pct??0,2,'%'):signed(movement?.net_raw_underlying_move_pct??0,2,'%');
  const chartLabel=unit==='R'?'Cumulative Strategy R':unit==='DIRECTIONAL'?'Cumulative Directional Move':'Raw Underlying Movement';
  const chartQuestion=unit==='R'?'Is the strategy growing?':unit==='DIRECTIONAL'?
    'Did Parlay correctly predict the direction of the underlying?':'How did the underlying price move?';
  const glanceText=unit==='R'?(metrics?.resolved_signals?
    `${metrics.resolved_signals} resolved plays have produced ${signed(metrics.cumulative_r,2,'R')} with ${metrics.average_r>0?'positive':metrics.average_r<0?'negative':'flat'} expectancy of ${signed(metrics.average_r,3,'R')} per play.`:
    'No resolved plays are available for strategy performance yet.'):
    unit==='DIRECTIONAL'?(movement?.resolved_with_prices?
      `${movement.positive_direction_rate}% of ${movement.resolved_with_prices} priced, resolved plays moved in the predicted direction. This measures the underlying, not option P/L or portfolio return.`:
      'No priced, resolved plays are available for directional accuracy yet.'):
      (movement?.resolved_with_prices?
        `Across ${movement.resolved_with_prices} priced, resolved plays, the sum of raw underlying price moves is ${signed(movement.net_raw_underlying_move_pct,2,'%')}. This sum is not an investment return.`:
        'No priced, resolved plays are available for raw underlying movement yet.');
  const pagination=data?.pagination;
  const first=pagination&&pagination.total_items>0?(pagination.page-1)*pagination.page_size+1:0;
  const last=pagination?Math.min(pagination.page*pagination.page_size,pagination.total_items):0;
  return <section id="performance" className="performance-page">
    <div className="performance-title"><div><p className="eyebrow">Visual play history · automated · one ticker per day</p><h2>Play History &amp; Performance</h2><p>See the shape of the strategy first, then open any play for its full evidence.</p></div>{data&&<span>{strategyName(strategy)}</span>}</div>
    <div className="performance-controls"><div><span>Strategy</span><div className="filter-tabs">{([['ONE_MIN_0DTE','True 0DTE'],['STRUCTURED_INTRADAY','Structured 5–14 DTE']] as [PerformanceStrategy,string][]).map(([value,label])=><button className={strategy===value?'active':''} onClick={()=>{setStrategy(value);setView('ALL');setPage(1);setExpanded('')}} key={value}>{label}</button>)}</div></div><div className="performance-unit-control"><span>Graph unit</span><div className="performance-unit-groups"><div className="performance-unit-group strategy-unit"><span>Strategy Performance</span><div className="filter-tabs"><button type="button" aria-pressed={unit==='R'} className={unit==='R'?'active':''} onClick={()=>setUnit('R')}>Strategy R</button></div></div><div className="performance-unit-group market-unit"><span>Market Movement</span><div className="filter-tabs"><button type="button" aria-pressed={unit==='DIRECTIONAL'} className={unit==='DIRECTIONAL'?'active':''} onClick={()=>setUnit('DIRECTIONAL')}>Directional Move</button><button type="button" aria-pressed={unit==='RAW'} className={unit==='RAW'?'active':''} onClick={()=>setUnit('RAW')}>Raw Underlying</button></div></div></div><p className="performance-unit-hint">R = strategy performance normalized by trade risk</p></div></div>
    <div className="filter-tabs source-tabs">{(['ALL','OPEN','COMPLETED','EXCLUDED'] as LedgerView[]).map(value=><button className={view===value?'active':''} onClick={()=>{setView(value);setPage(1);setExpanded('')}} key={value}>{value}</button>)}</div>
    {error&&<div className="performance-error" role="alert"><strong>Performance unavailable</strong><span>{error}</span></div>}
    {loading&&!data&&<div className="performance-loading">Building performance graphs…</div>}
    {data&&<>
      <div className="selection-summary"><span>Every engine fire</span><strong>{data.raw_metrics.total_triggered_signals} raw BUY alerts</strong><i>→</i><span>Account-like view</span><strong>{data.metrics.total_triggered_signals} first ticker-day plays</strong></div>
      <section className={`performance-at-glance ${unit==='R'?'strategy-glance':'market-glance'}`} aria-label="At a Glance"><header><span>AT A GLANCE</span><strong>{unit==='R'?'Strategy Performance':'Market Movement'}</strong></header><div className="glance-stats">{glanceCards.map(([label,value])=><div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><p>{glanceText}</p></section>
      <section className={`performance-measure-panel ${unit==='R'?'strategy-measure':'market-measure'}`} aria-label={unit==='R'?'Strategy Performance metrics':'Market Movement metrics'}><div className="performance-measure-heading"><span>{unit==='R'?'STRATEGY PERFORMANCE':'MARKET MOVEMENT'}</span><h3>{unit==='R'?'Risk-normalized play results':unit==='DIRECTIONAL'?'Direction-adjusted underlying price movement':'Raw underlying price movement'}</h3><p>{unit==='R'?`Each resolved play is measured against its original entry-to-stop risk. Win Rate counts positive-R plays; Profit Factor compares positive and negative R; Max Drawdown is the largest fall from a prior R peak. ${metrics?.quality_exclusions??0} selected plays are quality-excluded.`:unit==='DIRECTIONAL'?'Calls keep the underlying price move; puts reverse its sign. This is not option P/L or portfolio return.':"Shows price movement of the underlying, not the option trade's return. Calls and puts are not direction-adjusted in this view."}</p></div><div className="performance-metrics headline-metrics">{metricCards.map(([label,value])=><div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></section>
      <div className={`performance-chart-grid ${unit==='R'?'strategy-charts':'market-charts'}`}>
        <section className="graph-panel graph-wide"><header><div><span>{chartLabel}</span><h3>{chartQuestion}</h3></div><strong>{headline}</strong></header><CumulativeChart points={graphData} unit={unit}/></section>
        <section className="graph-panel"><header><div><span>DAY BY DAY</span><h3>{unit==='R'?'Where gains and losses happened':unit==='DIRECTIONAL'?'When direction was right or wrong':'When underlying prices rose or fell'}</h3></div></header><DailyBars points={graphData} unit={unit}/></section>
        <section className="graph-panel"><header><div><span>OUTCOME MIX</span><h3>How plays finished</h3></div><strong>{data.metrics.resolved_signals} resolved</strong></header><OutcomeGraph data={data.chart_data.outcomes}/></section>
      </div>
      <section className="option-shadow"><header><div><span>REAL OPTION EVIDENCE · FORWARD ONLY</span><h3>Automated ask-to-bid shadow</h3></div><strong>{data.option_shadow_metrics.quote_coverage_percent}% quote coverage</strong></header><div className="shadow-layout"><OptionEquityChart points={data.chart_data.daily}/><div className="shadow-stats"><div><span>Tracked</span><strong>{data.option_shadow_metrics.tracked_positions}</strong></div><div><span>Closed with quote</span><strong>{data.option_shadow_metrics.closed_with_quote}</strong></div><div><span>Quote gaps</span><strong>{data.option_shadow_metrics.quote_gaps}</strong></div><div><span>Shadow P/L</span><strong>{dollars.format(data.option_shadow_metrics.cumulative_pnl_dollars)}</strong></div><p>Entry is the verified ask. Exit is the first verified bid after the underlying exit. This never mixes into underlying-R headlines.</p></div></div></section>
      <div className="play-log-heading"><div><p className="eyebrow">THE PLAYS</p><h3>{view==='ALL'?'Every selected play':view.charAt(0)+view.slice(1).toLowerCase()}</h3><p>{first}–{last} of {pagination?.total_items??0} · newest first</p></div><label>Rows per page<select value={pageSize} onChange={event=>{setPageSize(Number(event.target.value));setPage(1)}}>{PAGE_SIZES.map(size=><option key={size} value={size}>{size}</option>)}</select></label></div>
      {data.signals.length===0?<div className="play-log-empty">No plays match this view.</div>:<div className="performance-play-grid">{data.signals.map(row=><PlayCard row={row} unit={unit} expanded={expanded===row.signal_id} onToggle={()=>setExpanded(expanded===row.signal_id?'':row.signal_id)} key={row.signal_id}/>)}</div>}
      {pagination&&<nav className="pagination" aria-label="Performance log pages"><button type="button" disabled={loading||pagination.page<=1} onClick={()=>{setPage(value=>value-1);setExpanded('')}}>← Previous</button><span>Page <strong>{pagination.page}</strong> of <strong>{pagination.total_pages}</strong></span><button type="button" disabled={loading||pagination.page>=pagination.total_pages} onClick={()=>{setPage(value=>value+1);setExpanded('')}}>Next →</button></nav>}
      <p className="performance-method"><strong>Research boundary:</strong> Strategy R uses underlying-path outcomes normalized by original risk. Market Movement shows underlying price changes, not option or portfolio returns. Manual positions and backtests remain excluded. Raw repeated alerts remain visible only in aggregate counts.</p>
    </>}
  </section>;
}
