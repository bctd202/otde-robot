import {useEffect,useState} from 'react';
import {getRetestResearch} from '../api/client';
import './retest-research.css';

export interface RetestResponse {
  status:string; note:string; verdict?:string; baseline_opportunities?:number; input_coverage?:number|null;
  activated_at?:string; spec_hash?:string;
  accounts?:{key:string;arm:string;scenario:string;complete:boolean;net_pnl_cents:number|null;
    max_drawdown_cents:number|null;unresolved:number;entry_quote_coverage:number|null;exit_quote_coverage:number|null;
    daily:{date:string;equity_cents:number|null;complete:boolean}[]}[];
  latest?:{at:string;accounts:Record<string,{equity_cents:number|null}>}|null;
  positions?:{id:number;ticker:string;arm:string;scenario:string;status:string;detail:{reason:string|null;net_pnl_cents:number|null;
    opportunity_outcome?:{reason:string;at:string|null}|null}}[];
  pagination?:{page:number;pages:number;total:number};
}
const dollars=(c:number|null|undefined)=>c==null?'Unknown':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(c/100);
const percent=(v:number|null|undefined)=>v==null?'Not measured':`${v.toFixed(1)}%`;

function Equity({points}:{points:NonNullable<RetestResponse['accounts']>[number]['daily']}){
  const known=points.flatMap(p=>p.equity_cents===null?[]:[p.equity_cents]);
  if(!known.length)return <p>No observed liquidation values yet. Missing data is not zero.</p>;
  const low=Math.min(200000,...known),high=Math.max(200000,...known),range=Math.max(100,high-low);
  const segments:string[]=[];let segment:string[]=[];
  points.forEach((p,i)=>{if(p.equity_cents===null){if(segment.length)segments.push(segment.join(' '));segment=[];return}
    segment.push(`${30+i/Math.max(1,points.length-1)*640},${180-(p.equity_cents-low)/range*140}`)});
  if(segment.length)segments.push(segment.join(' '));
  return <svg viewBox="0 0 700 240" role="img" aria-label="Observed research account value; gaps remain unknown">
    <text x="30" y="20">{dollars(high)}</text><text x="30" y="205">{dollars(low)}</text>
    {segments.map((s,i)=><polyline key={i} points={s} fill="none" stroke="currentColor" strokeWidth="3"/>)}
    {segments.flatMap(s=>s.split(' ')).map((p,i)=>{const [x,y]=p.split(',');return <circle key={i} cx={x} cy={y} r="3" fill="currentColor"/>})}
    <text x="30" y="230">{points[0]?.date}</text><text x="670" y="230" textAnchor="end">{points.at(-1)?.date}</text>
  </svg>;
}

export function RetestResearch({active}:{active:boolean}){
  const [data,setData]=useState<RetestResponse|null>(null),[error,setError]=useState('');
  const [page,setPage]=useState(1),[view,setView]=useState<'accounts'|'opportunities'>('accounts');
  const [selected,setSelected]=useState(''),[refresh,setRefresh]=useState(0);
  useEffect(()=>{if(!active)return;let cancelled=false;setError('');setData(null);
    void getRetestResearch(page,view).then(value=>{if(!cancelled)setData(value)}).catch(reason=>{
      if(!cancelled)setError(reason instanceof Error?reason.message:'Research report unavailable')});
    return()=>{cancelled=true};},[active,page,view,refresh]);
  const account=data?.accounts?.find(a=>a.key===selected)??data?.accounts?.[0];
  return <section className="retest-research" aria-label="Prospective breakout and retest research">
    <header><div><p className="eyebrow">Forward paper research · separate accounts</p><h2>Breakout vs. retest</h2></div>
      <button type="button" onClick={()=>setRefresh(n=>n+1)}>Refresh research</button></header>
    {error&&<p role="alert">{error}</p>}
    {!data&&!error&&<p>Loading research status…</p>}
    {data&&<><p><strong>{data.status==='NOT_ACTIVATED'?'Not activated':data.status==='COLLECTING'?'Collecting — no conclusion yet':'Collection window ended'}</strong></p>
      <p>{data.note}</p>
      {data.status!=='NOT_ACTIVATED'&&<>
        <div className="retest-metrics"><p>First one-minute opportunities <b>{data.baseline_opportunities}</b></p>
          <p>Required input coverage <b>{percent(data.input_coverage)}</b></p>
          <p>Evaluation <b>{data.verdict?.replaceAll('_',' ')}</b></p></div>
        <label>Independent account<select value={account?.key??''} onChange={e=>setSelected(e.target.value)}>
          {data.accounts?.map(a=><option key={a.key} value={a.key}>{a.arm==='control'?'Immediate breakout':'Wait for retest'} · {a.scenario==='stress'?'3¢/side stress':'existing costs'}</option>)}
        </select></label>
        {account&&<><h3>{account.arm==='control'?'Immediate breakout':'Wait for retest'} — observed account value</h3>
          <p>Latest observed value: <strong>{dollars(data.latest?.accounts[account.key]?.equity_cents)}</strong>{data.latest?` · ${data.latest.at}`:''}. Each account starts at $2,000; never add the experiments together.</p>
          <Equity points={account.daily}/>
          <div className="retest-metrics"><p>Entry quote coverage <b>{percent(account.entry_quote_coverage)}</b></p>
            <p>Exit quote coverage <b>{percent(account.exit_quote_coverage)}</b></p>
            <p>Unresolved positions <b>{account.unresolved}</b></p></div>
          <p>{account.complete?`Complete net result: ${dollars(account.net_pnl_cents)}.`:'Account-performance verdict withheld until the 60-session window and evidence checks are complete.'}</p></>}
        <div className="filter-tabs"><button type="button" aria-pressed={view==='accounts'} onClick={()=>{setView('accounts');setPage(1)}}>Account decisions</button>
          <button type="button" aria-pressed={view==='opportunities'} onClick={()=>{setView('opportunities');setPage(1)}}>Uncapped opportunities</button></div>
        {view==='opportunities'&&<p>These observations ignore cash/slot limits. They are not a funded portfolio or a return you could necessarily capture.</p>}
        <div className="retest-trades">{data.positions?.map(p=><article key={p.id}><strong>{p.ticker} · {p.arm} · {p.scenario}</strong>
          <span>{p.status.replaceAll('_',' ')}</span><p>{p.detail.reason?.replaceAll('_',' ')}</p>
          {p.detail.opportunity_outcome&&<p>Underlying path: {p.detail.opportunity_outcome.reason.replaceAll('_',' ')}. Not an option return.</p>}
          {p.detail.net_pnl_cents!==null&&<p>Modeled trade result: {dollars(p.detail.net_pnl_cents)}</p>}</article>)}</div>
        {data.pagination&&<nav className="retest-pagination" aria-label="Research decisions pages">
          <button disabled={data.pagination.page<=1} onClick={()=>setPage(p=>p-1)}>Previous</button>
          <span>Page {data.pagination.page} of {data.pagination.pages}</span>
          <button disabled={data.pagination.page>=data.pagination.pages} onClick={()=>setPage(p=>p+1)}>Next</button></nav>}
        <details><summary>Frozen research identity</summary><p>Activated {data.activated_at}</p><code>{data.spec_hash}</code></details>
      </>}
    </>}
  </section>;
}
