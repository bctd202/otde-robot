import {useEffect,useState} from 'react';
import {getForwardPaperAccount} from '../api/client';
import {formatEasternDateTime} from '../lib/dates';
import type {ForwardAccount,PaperAccountChoice} from '../types';
import {AccountEquityChart} from './AccountEquityChart';
import {TradeResultCards} from './TradeResultCards';
import {AccountCapacity} from './AccountCapacity';

const money=(cents:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100);
const human=(text:string)=>text.replaceAll('_',' ').toLowerCase();

function MoneyChart({daily,field,title}:{daily:ForwardAccount['daily'];field:'cash_cents'|'realized_cents';title:string}){
  const width=640,height=210,left=65,right=15,top=20,bottom=35;
  const values=daily.map(d=>d[field]);
  const min=Math.min(0,...values),max=Math.max(100,...values);
  const x=(i:number)=>left+(daily.length===1?.5:i/(daily.length-1))*(width-left-right);
  const y=(value:number)=>top+(max-value)/(max-min)*(height-top-bottom);
  return <svg className="performance-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
    {[0,.5,1].map(t=>{const value=min+t*(max-min);return <g key={t}><line className="graph-grid" x1={left} x2={width-right} y1={y(value)} y2={y(value)}/><text className="graph-axis" x={left-6} y={y(value)+4} textAnchor="end">{money(value)}</text></g>})}
    <polyline className="graph-line" points={values.map((v,i)=>`${x(i)},${y(v)}`).join(' ')}/>
    {daily.map((d,i)=><circle className="graph-point" key={d.date} cx={x(i)} cy={y(d[field])} r="4"><title>{d.date}: {money(d[field])}</title></circle>)}
    {daily.length>0&&<><text className="graph-axis" x={left} y={height-8}>{daily[0].date}</text><text className="graph-axis" textAnchor="end" x={width-right} y={height-8}>{daily[daily.length-1].date}</text></>}
  </svg>;
}

export function ForwardPaperAccount(){
  const [data,setData]=useState<ForwardAccount|null>(null);
  const [page,setPage]=useState(1);
  const [pane,setPane]=useState<'ACCOUNT'|'TRADES'|'DETAILS'>('ACCOUNT');
  const [accountKey,setAccountKey]=useState<string|undefined>(()=>new URLSearchParams(window.location.search).get('paper_account')??undefined);
  const [accounts,setAccounts]=useState<PaperAccountChoice[]>([]);
  const [status,setStatus]=useState('Loading the forward account…');
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;
    const load=()=>getForwardPaperAccount(page,accountKey).then(result=>{
      if(!active)return;
      setAccounts(result.accounts??[]);
      if(result.status==='SCHEDULED'||result.status==='NOT_STARTED'){
        setData(null);setStatus(result.status==='SCHEDULED'
          ? `Scheduled for ${formatEasternDateTime(result.scheduled_start!)}. A separate ${money(result.starting_cash_cents!)} paper trial will start when the scanner next processes the account on or after that time. No old trades or positions will be imported.`
          : result.activation_required?'Not started. The ten-position account is prepared but requires explicit after-hours activation. No funding or historical trades have been imported. Select the existing trial to inspect its preserved balance.':'Not started. Waiting for the scanner to initialize the corrected trial. Historical plays will not be imported.');setError('');return;
      }
      if((result.status!=='ACTIVE'&&result.status!=='ARCHIVED')||!Array.isArray(result.events)||!result.policy)throw new Error('Invalid account response');
      setData(result);setError('');
    }).catch(()=>{if(active)setError('Account update unavailable. Any figures below are the last saved response, not a live balance.')});
    void load();const timer=window.setInterval(()=>{void load()},30000);
    return()=>{active=false;window.clearInterval(timer)};
  },[page,accountKey]);
  return <section className="forward-account graph-panel" aria-label="Forward simulated cash account">
    <header><div><span>FORWARD CASH ACCOUNT · SIMULATED, NOT BROKER FILLS</span><h3>What could this account actually keep?</h3></div><strong>{data?`${money(data.policy.starting_cash_cents)} starting cash`:'New account'}</strong></header>
    <p>Both automated engines share this account. Lotto and manual trades stay separate. History filters and replay sliders below do not change it.</p>
    {accounts.length>0&&<label className="account-trial-selector">Paper trial <select value={accountKey??accounts[0].key} onChange={event=>{setAccountKey(event.target.value);setPage(1);setData(null);setError('');setStatus('Loading selected account…')}}>{accounts.map(account=><option key={account.key} value={account.key}>{account.label}</option>)}</select></label>}
    {error&&<p role="alert" className="execution-warning">{error}</p>}
    {!data&&!error&&<p>{status}</p>}
    {data&&<>
      <nav className="workspace-tabs" aria-label="Cash account sections">{(['ACCOUNT','TRADES','DETAILS'] as const).map(value=><button key={value} aria-current={pane===value?'page':undefined} onClick={()=>{setPane(value);setPage(1)}}>{value==='ACCOUNT'?'Balance':value==='TRADES'?'Trades':'Account details'}</button>)}</nav>
      {data.status==='ARCHIVED'?<p className="execution-warning">Legacy research — read-only. These balances and position states are preserved, not settled or forgiven. Held exposure remains unknown; no new entries, exits or settlements are processed here. It is not included in the corrected trial.</p>:<p>{data.policy.label??'Corrected Tastytrade trial'} — its own starting capital, saved rules and results. Restarting does not reset it. Other accounts remain separate; do not add their balances or overlapping trades together.</p>}
      <p className="forward-account-dates">Started {formatEasternDateTime(data.activated_at)} · Account last processed {formatEasternDateTime(data.processed_at)} · Snapshot {formatEasternDateTime(data.as_of)}</p>
      {data.processing_stale&&<p role="alert" className="execution-warning">Account processing is behind during market hours. Check scanner health; these figures do not confirm that new entries or exits are being tracked.</p>}
      <AccountCapacity account={data}/>
      {pane==='ACCOUNT'&&<AccountEquityChart key={data.account_key} account={data}/>}
      {pane!=='DETAILS'&&data.unpriced_positions>0&&<p className="execution-warning">Account result is incomplete: {data.unpriced_positions} held position(s) have unknown value—not zero. Open Account details for the preserved exposure.</p>}
      {pane==='TRADES'&&<><TradeResultCards trades={data.trades??[]}/><nav className="forward-pagination" aria-label="Paper trade pages"><button disabled={page<=1} onClick={()=>setPage(value=>value-1)}>Previous trades</button><span>Page {data.trade_pagination?.page??1} of {data.trade_pagination?.pages??1}</span><button disabled={page>=(data.trade_pagination?.pages??1)} onClick={()=>setPage(value=>value+1)}>Next trades</button></nav></>}
      {pane==='DETAILS'&&<>
      <div className="performance-metrics headline-metrics">
        {[
          ['Net realized P/L',money(data.realized_cents)],
          ['Settled cash',money(data.settled_cents)],
          ['Available to enter',money(data.available_cents)],
          ['Unsettled proceeds',money(data.unsettled_cents)],
          ['Estimated liquidation equity',data.equity_cents===null?'Incomplete':money(data.equity_cents)],
          ['Costs charged so far',money(data.charged_fees_cents)],
        ].map(([label,value])=><div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}
      </div>
      <p>Realized P/L includes opening and closing costs for completed simulated trades only. Cash is not profit. {money(data.reserved_exit_fees_cents)} is reserved for closing costs; {money(data.open_entry_fees_cents)} of charged costs belong to positions not yet closed.</p>
      {data.unpriced_positions>0&&<p className="execution-warning">Account result is incomplete: {data.unpriced_positions} held position(s), with {money(data.unpriced_debit_cents)} in entry debits, lack a fresh liquidation price. Their value is unknown—not zero, and not their purchase cost.</p>}
      <div className="performance-chart-grid">
        <div><h4>Net realized P/L · after modeled costs</h4><MoneyChart daily={data.daily} field="realized_cents" title="Forward account net realized P/L"/></div>
        <div><h4>Cash held · settled + unsettled, excludes options</h4><MoneyChart daily={data.daily} field="cash_cents" title="Forward account cash held, not profit"/></div>
      </div>
      <details><summary>Frozen assumptions &amp; limitations</summary><p>One contract per entry; {data.policy.max_positions} simultaneous positions maximum. {money(data.policy.max_entry_cents)} maximum entry debit including closing-cost reserve. Ask + {money(data.policy.slippage_premium_cents)} premium at entry; bid − {money(data.policy.slippage_premium_cents)} premium at exit, floored at zero. Options use a 100-share multiplier.</p><p>Opening commission {money(data.policy.opening_commission_cents)}; closing commission {money(data.policy.closing_commission_cents)}. Additional fee allowance {money(data.policy.fee_allowance_per_side_cents)} per side is an assumption, not a broker invoice. Quotes must be live, exact-contract and at most {data.policy.quote_age_seconds}s old, after the decision. Fills happen on a later scanner observation, not the signal candle. Entry deadline {data.policy.entry_deadline_seconds}s; exit deadline {data.policy.exit_deadline_seconds}s after the exit request.</p><p>Unchanged underlying stop/target/time exits. Proceeds become available on the next eligible banking and market day at 9:30 ET, when the scanner processes settlement. No margin, partial fills, queue guarantees, assignment or exercise simulation. Missing exit prices stay unresolved and consume a position slot. Settings changes cannot reset this account or rewrite its policy. This is a more constrained estimate—not proof of executable returns.</p></details>
      <h4>Pending entries and money still in flight</h4>
      {data.positions.length===0?<p>No pending entries, held positions or unsettled sales.</p>:<div className="forward-ledger-scroll"><table><thead><tr><th>Contract</th><th>State</th><th>Entry debit</th><th>Details</th></tr></thead><tbody>{data.positions.map(p=><tr key={p.id}><td>{p.option_symbol}</td><td>{human(p.status)}</td><td>{p.entry_debit_cents==null?'—':money(p.entry_debit_cents)}</td><td>{p.reason??(p.settles_at?`Settlement eligible ${formatEasternDateTime(p.settles_at)}`:p.status==='UNSETTLED'?'Settlement calendar unavailable—cash held':p.exit_requested_at?'Waiting for a post-exit quote':'Waiting for fresh evidence')}</td></tr>)}</tbody></table></div>}
      <h4>Money ledger · every debit, sale, settlement and skip</h4>
      <div className="forward-ledger-scroll"><table><thead><tr><th>Time (ET)</th><th>Event</th><th>Settled cash Δ</th><th>Unsettled Δ</th><th>Evidence</th></tr></thead><tbody>{data.events.map(e=><tr key={e.id}><td>{formatEasternDateTime(e.at)}</td><td>{human(e.kind)}</td><td>{money(e.settled_cents)}</td><td>{money(e.unsettled_cents)}</td><td><details><summary>{e.detail.ticker??'Account'} · {e.detail.reason??'View saved evidence'}</summary><pre>{JSON.stringify(e.detail,null,2)}</pre></details></td></tr>)}</tbody></table></div>
      <div className="forward-pagination"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)}>Previous cash events</button><span>Page {data.pagination.page} of {data.pagination.pages} · {data.pagination.total} events</span><button disabled={page>=data.pagination.pages} onClick={()=>setPage(p=>p+1)}>Next cash events</button></div>
      </>}
    </>}
  </section>;
}
