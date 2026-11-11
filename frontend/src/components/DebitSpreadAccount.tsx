import {useEffect,useState} from 'react';
import './debit-spread-account.css';
import {getDebitSpreadAccount} from '../api/client';
import {formatEasternDateTime} from '../lib/dates';
import type {DebitSpreadAccountData} from '../types';

const money=(v:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(v/100);
const human=(v:string)=>v.replaceAll('_',' ').toLowerCase();

export function DebitSpreadAccount({active=false}:{active?:boolean}){
  const [data,setData]=useState<DebitSpreadAccountData|null>(null),[error,setError]=useState('');
  const [page,setPage]=useState(1),[unit,setUnit]=useState<'VALUE'|'RETURN'>('VALUE');
  const [range,setRange]=useState<'ALL'|'1D'>('ALL');
  useEffect(()=>{
    if(!active)return;
    let current=true;
    const load=()=>getDebitSpreadAccount(page).then(value=>{if(current){setData(value);setError('')}})
      .catch(()=>{if(current)setError('Spread account unavailable. Any figures below are the last saved response.')});
    void load();const timer=window.setInterval(()=>void load(),30000);
    return()=>{current=false;window.clearInterval(timer)};
  },[active,page]);
  const history=data?.history??[];
  const day=(at:string)=>new Date(at).toLocaleDateString('en-CA',{timeZone:'America/New_York'});
  const daily=new Map<string,typeof history[number]>();
  history.forEach(p=>daily.set(day(p.at),p));
  const lastDay=history.length?day(history[history.length-1].at):'';
  const points=range==='ALL'?[...daily.values()]:history.filter(p=>day(p.at)===lastDay);
  const values=points.flatMap(p=>p.equity_cents===null?[]:[unit==='VALUE'?p.equity_cents:(p.equity_cents/200000-1)*100]);
  const low=Math.min(unit==='VALUE'?200000:0,...values),high=Math.max(low+(unit==='VALUE'?100:1),...values);
  const x=(i:number)=>65+(points.length===1?.5:i/Math.max(1,points.length-1))*555;
  const y=(v:number)=>22+(high-v)/(high-low)*170;
  const segments:{at:string;index:number;value:number}[][]=[];
  points.forEach((p,index)=>{
    const previous=points[index-1];
    if(index===0||p.equity_cents===null||previous?.equity_cents===null||(range==='1D'&&Date.parse(p.at)-Date.parse(previous.at)>180000))segments.push([]);
    if(p.equity_cents!==null)segments[segments.length-1].push({at:p.at,index,value:unit==='VALUE'?p.equity_cents:(p.equity_cents/200000-1)*100});
  });
  const known=data?.status!=='NOT_ACTIVATED'&&data?.equity_cents!==null&&data?.equity_cents!==undefined;
  return <section id="debit-spreads" className="forward-account graph-panel debit-spread-account" aria-label="Independent debit-spread paper account">
    <header><div><span>SEPARATE PAPER EXPERIMENT · TWO-LEG OPTIONS</span><h3>Debit spreads</h3></div><strong>{data?.status==='NOT_ACTIVATED'?'Not funded':data?.status==='PAUSED'?'Processing paused':'Paper research'}</strong></header>
    <p>Same qualifying signals and expiration; one long option plus one short hedge. Existing main, lotto and breakout/retest accounts continue independently.</p>
    {error&&<p role="alert">{error}</p>}
    {!data&&!error&&<p>{active?'Loading spread account…':'Open Research to inspect this separate account.'}</p>}
    {data?.status==='NOT_ACTIVATED'&&<><h4>Prepared · not activated</h4><p>$2,000 planned starting cash · $250 all-in per spread · ten-position policy · no separate daily spending cap.</p><p>No money has been funded and no historical trades have been imported. Enabling the feature alone does not activate it.</p></>}
    {data&&data.status!=='NOT_ACTIVATED'&&<>
      <nav className="workspace-tabs" aria-label="Spread graph units"><button aria-pressed={unit==='VALUE'} onClick={()=>setUnit('VALUE')}>Value $</button><button aria-pressed={unit==='RETURN'} onClick={()=>setUnit('RETURN')}>Return %</button></nav>
      <nav className="workspace-tabs" aria-label="Spread graph period"><button aria-pressed={range==='1D'} onClick={()=>setRange('1D')}>1D</button><button aria-pressed={range==='ALL'} onClick={()=>setRange('ALL')}>ALL</button></nav>
      <h4>{known?(unit==='VALUE'?money(data.equity_cents!):`${((data.equity_cents!/200000-1)*100).toFixed(2)}%`):'Account value incomplete'}</h4>
      <p>{data.unknown_positions} positions lack a current complete valuation. Gaps remain unknown; this graph never adds separate trade percentages.</p>
      {points.length>0?<svg className="performance-line-chart" viewBox="0 0 640 230" role="img" aria-label="Independent spread account value; unknown valuations break the line">
        {[low,high].map(v=><g key={v}><line className="graph-grid" x1="65" x2="620" y1={y(v)} y2={y(v)}/><text className="graph-axis" x="60" y={y(v)+4} textAnchor="end">{unit==='VALUE'?money(v):`${v.toFixed(1)}%`}</text></g>)}
        {segments.filter(s=>s.length).map((s,i)=><g key={i}><polyline className="graph-line" points={s.map(p=>`${x(p.index)},${y(p.value)}`).join(' ')}/>{s.map(p=><circle className="graph-point" key={p.at} cx={x(p.index)} cy={y(p.value)} r="3"><title>{formatEasternDateTime(p.at)}: {unit==='VALUE'?money(p.value):`${p.value.toFixed(2)}%`}</title></circle>)}</g>)}
      </svg>:<p>No saved account observations yet.</p>}
      <small>{range==='ALL'?"Each day’s last saved valuation; this does not show intraday drawdown.":'Latest recorded day. Missing valuations and intervals break the line.'}</small>
      <div className="research-cash-line"><span>Available settled cash</span><strong>{data.available_cents===null?'Pending liability evidence':money(data.available_cents??0)}</strong><small>Settled {money(data.settled_cents??0)} · unsettled {money(data.unsettled_cents??0)}</small></div>
      <p>Known realized P/L: {money(data.realized_cents??0)} · {data.held_positions} held · {data.pending_positions} pending · {data.skips} skipped opportunities.</p>
      <details><summary>Matched comparison with the main account</summary>
        <p>Same signal, entered in both accounts after this account started. Full account results and this selected comparison are different measures.</p>
        <p>{data.matched?.entered_pairs} matched entries · {data.matched?.closed_priced_pairs} closed and priced pairs · {data.matched?.unresolved_pairs} unresolved pairs.</p>
        <p>Closed subset only: spreads {money(data.matched?.spread_closed_subset_pnl_cents??0)} · main {money(data.matched?.baseline_closed_subset_pnl_cents??0)}.</p>
        {!data.matched?.complete&&<p>Complete comparison unavailable: unresolved or absent pairs remain visible.</p>}
        <p>Entry quote coverage: {data.entry_quote_coverage?.quoted}/{data.entry_quote_coverage?.requested} requested packages. Exit quote coverage: {data.exit_quote_coverage?.quoted}/{data.exit_quote_coverage?.requested} requested packages.</p>
      </details>
      <h4>Trades and opportunity log</h4>
      {data.positions?.map(p=><article className="run-result" key={p.id}><strong>{p.ticker} · {p.mode==='ONE_MIN_0DTE'?'1-minute':'Structured'} · {human(p.status)}</strong>
        {p.long?.normalized_option_symbol&&<p>Buy {p.long.normalized_option_symbol} · sell {p.short?.normalized_option_symbol}</p>}
        {p.entry_debit_cents!==undefined&&<p>Entry {money(p.entry_debit_cents)} · {p.net_pnl_cents===undefined?'Outcome pending':`net P/L ${money(p.net_pnl_cents)}`}</p>}
        {p.reason&&<small>{human(p.reason)}</small>}
      </article>)}
      <nav aria-label="Spread trade pages"><button disabled={page===1} onClick={()=>setPage(page-1)}>Previous</button><span> Page {data.page} of {data.pages} </span><button disabled={page>=(data.pages??1)} onClick={()=>setPage(page+1)}>Next</button></nav>
      <small>Ask/bid paper-package model with per-leg costs, not broker fills. Cached quotes only. Missing exits and possible assignment obligations are not assumed settled.</small>
    </>}
  </section>;
}
