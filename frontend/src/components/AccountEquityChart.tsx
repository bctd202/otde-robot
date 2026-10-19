import {useEffect,useRef,useState} from 'react';
import type {AccountEquityPoint,ForwardAccount} from '../types';
import {equitySegments} from '../lib/accountEquity';
import {formatEasternDateTime} from '../lib/dates';

const money=(cents:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100);
const percent=(value:number)=>`${value>0?'+':''}${value.toFixed(2)}%`;
const ranges=['1D','1W','1M','ALL'] as const;
type Range=typeof ranges[number];

export type EquityAccount=Pick<ForwardAccount,'status'|'account_key'|'as_of'|'processed_at'|'equity_cents'|'equity_history'>&{policy:{starting_cash_cents:number}};
export function AccountEquityChart({account}:{account:EquityAccount}){
  const [range,setRange]=useState<Range>('ALL');
  const [unit,setUnit]=useState<'PERCENT'|'DOLLARS'>('PERCENT');
  const [selectedAt,setSelectedAt]=useState<string|null>(null);
  const [width,setWidth]=useState(640);
  const container=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!container.current||typeof ResizeObserver==='undefined')return;
    const observer=new ResizeObserver(entries=>setWidth(Math.max(280,entries[0].contentRect.width)));
    observer.observe(container.current);return()=>observer.disconnect();
  },[]);
  const history=account.equity_history;
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(account.as_of));
  const cutoff=Date.parse(`${today}T00:00:00Z`)-(range==='1W'?7:30)*86400000;
  const points=(range==='1D'?history?.intraday:history?.daily)?.filter(point=>range==='ALL'||range==='1D'||Date.parse(`${point.date}T00:00:00Z`)>=cutoff)??[];
  const selected=points.find(point=>point.at===selectedAt);
  const equity=selected?selected.equity_cents:account.equity_cents;
  const starting=account.policy.starting_cash_cents;
  const change=equity===null?null:equity-starting;
  const performance=change===null?null:change/starting*100;
  const value=(point:AccountEquityPoint)=>unit==='PERCENT'?point.return_percent!:point.equity_cents!;
  const priced=points.filter(point=>point.equity_cents!==null&&point.return_percent!==null);
  const baseline=unit==='PERCENT'?0:starting;
  const values=[baseline,...priced.map(value)];
  const low=Math.min(...values),high=Math.max(...values);
  const padding=Math.max((high-low)*.15,unit==='PERCENT'?.1:100);
  const min=low-padding,max=high+padding;
  const height=250,left=unit==='PERCENT'?60:80,right=16,top=16,bottom=40;
  const from=points.length?Date.parse(points[0].at):0,to=points.length?Date.parse(points[points.length-1].at):from;
  const x=(point:AccountEquityPoint)=>left+(to===from?.5:(Date.parse(point.at)-from)/(to-from))*(width-left-right);
  const y=(amount:number)=>top+(max-amount)/(max-min)*(height-top-bottom);
  const segments=equitySegments(points,range==='1D');
  const axis=(amount:number)=>unit==='PERCENT'?percent(amount):money(amount);
  const pointLabel=(point:AccountEquityPoint)=>`${formatEasternDateTime(point.at)}: ${point.equity_cents===null?'Unpriced':`${money(point.equity_cents)} · ${percent(point.return_percent!)}`}`;
  return <section className="account-equity" aria-label="Account value and percentage return">
    <div className="account-equity-heading"><div><span>OPTION-DOLLAR ACCOUNT VALUE · SIMULATED</span><h4>{equity===null?'Value incomplete':money(equity)}</h4>
      <p className={performance===null?'':performance>=0?'positive-text':'negative-text'}>{change===null?'Return unavailable while positions are unpriced':`${change>0?'+':''}${money(change)} (${percent(performance!)}) since funding`}</p>
      <small>{selected?`Saved observation · ${formatEasternDateTime(selected.at)}`:account.status==='ARCHIVED'?`Archived account · last processed ${formatEasternDateTime(account.processed_at)}`:`Current estimate · ${formatEasternDateTime(account.as_of)}`}</small></div>
      <div className="equity-controls" role="group" aria-label="Account graph units">{(['PERCENT','DOLLARS'] as const).map(option=><button type="button" aria-pressed={unit===option} onClick={()=>setUnit(option)} key={option}>{option==='PERCENT'?'Return %':'Value $'}</button>)}</div>
    </div>
    <div className="equity-controls" role="group" aria-label="Account graph range">{ranges.map(option=><button type="button" aria-pressed={range===option} onClick={()=>{setRange(option);setSelectedAt(null)}} key={option}>{option}</button>)}</div>
    <div ref={container}>
      {points.length===0?<p className="equity-empty">No saved equity observations in this range. {account.status==='ARCHIVED'?'This account is archived; missing history will not be backfilled.':'This graph starts collecting when the trial is initialized; old trades are not converted into invented account returns.'}</p>:<>
        <svg className="account-equity-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={unit==='PERCENT'?'Paper account percentage return since funding':'Paper account liquidation value in dollars'}
          onPointerMove={event=>{const rect=event.currentTarget.getBoundingClientRect();const at=from+((event.clientX-rect.left)/rect.width*width-left)/(width-left-right)*(to-from);setSelectedAt(points.reduce((nearest,point)=>Math.abs(Date.parse(point.at)-at)<Math.abs(Date.parse(nearest.at)-at)?point:nearest).at)}}>
          {[0,.5,1].map(t=>{const amount=min+t*(max-min);return <g key={t}><line className="graph-grid" x1={left} x2={width-right} y1={y(amount)} y2={y(amount)}/><text className="graph-axis" x={left-8} y={y(amount)+4} textAnchor="end">{axis(amount)}</text></g>})}
          <line className="equity-baseline" x1={left} x2={width-right} y1={y(baseline)} y2={y(baseline)}/>
          {segments.map((segment,index)=><polyline data-testid="equity-segment" className="graph-line" key={index} points={segment.map(point=>`${x(point)},${y(value(point))}`).join(' ')}/>)}
          {priced.map(point=><circle className="graph-point" key={point.at} cx={x(point)} cy={y(value(point))} r={point.at===selectedAt?6:3}><title>{pointLabel(point)}</title></circle>)}
          <text className="graph-axis" x={left} y={height-12}>{range==='1D'?new Date(points[0].at).toLocaleTimeString('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit'}):points[0].date}</text>
          <text className="graph-axis" textAnchor="end" x={width-right} y={height-12}>{range==='1D'?new Date(points[points.length-1].at).toLocaleTimeString('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit'}):points[points.length-1].date}</text>
        </svg>
        <label className="equity-inspect">Inspect saved account value<input type="range" min="0" max={Math.max(0,points.length-1)} value={Math.max(0,selected?points.indexOf(selected):points.length-1)} onChange={event=>setSelectedAt(points[Number(event.target.value)].at)} aria-valuetext={pointLabel(selected??points[points.length-1])}/></label>
        <button type="button" className="equity-current" onClick={()=>setSelectedAt(null)}>{account.status==='ARCHIVED'?'Show archived account':'Show current estimate'}</button>
      </>}
    </div>
    <p className="equity-method">Cash + verified open-option bid value − modeled exit costs. Percentage = change in account value ÷ original {money(starting)} funding. This is not summed trade percentages or underlying R. Range controls change visible dates, not the funding baseline.</p>
    <small>1D shows the latest recorded day; longer ranges show each day's last observation. Unknown prices and missing intraday intervals break the line. {history?.started_at?`Saved observations begin ${formatEasternDateTime(history.started_at)}.`:account.status==='ARCHIVED'?'No equity observations were saved for this account.':'Observations begin with trial initialization.'} Quote-based valuations are not broker-confirmed fills.</small>
  </section>;
}
