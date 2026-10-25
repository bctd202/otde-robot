import {useEffect,useState} from 'react';
import {getLottoPaperTrial} from '../api/client';
import type {LottoTrialResponse} from '../types';
import {formatEasternDateTime} from '../lib/dates';
import {AccountEquityChart} from './AccountEquityChart';
import {TradeResultCards} from './TradeResultCards';

export function LottoForward({onInspect}:{onInspect:(id:string)=>void}){
  const [data,setData]=useState<LottoTrialResponse|null>(null);
  const [key,setKey]=useState<string>();
  const [page,setPage]=useState(1);
  const [error,setError]=useState('');
  const [pane,setPane]=useState<'BALANCE'|'TRADES'>('BALANCE');
  useEffect(()=>{
    let active=true;
    const load=()=>getLottoPaperTrial(page,key).then(result=>{if(!Array.isArray(result.accounts)||!result.accounts.length||!result.accounts.every(a=>a.key&&a.label&&['combined','directional'].includes(a.scope)))throw new Error('Invalid account response');if(active){setData(result);setError('')}})
      .catch(()=>{if(active)setError('Lotto account unavailable. Any displayed figures are the last response, not a live balance.')});
    void load();const timer=window.setInterval(()=>void load(),30000);
    return()=>{active=false;window.clearInterval(timer)};
  },[key,page]);
  return <section className="forward-account graph-panel" aria-label="Forward lotto paper accounts">
    <h3>What did the lotto rules actually keep?</h3><p>Two exit-rule experiments: 5× trigger versus a 40% trail after 2×. Each starts with $500 shared by calls and puts. Never add these balances together. No brokerage orders.</p>
    <p>Each shared account has one open idea across calls and puts, one contract per ticker/day, and a combined $100 daily all-in cap. The two exit rules run independently, so later entries can differ. Model: $1.50 opening costs, $0.50 closing costs, plus 1¢ premium slippage each side.</p>
    {data&&<label className="account-trial-selector">Lotto experiment <select value={key??data.account_key} onChange={e=>{setKey(e.target.value);setPage(1);setData(null);setError('')}}>
      <optgroup label="Shared calls + puts · $500 each">{data.accounts.filter(a=>a.scope==='combined').map(a=><option key={a.key} value={a.key}>{a.label}</option>)}</optgroup>
      <optgroup label="Original directional comparisons · $500 each">{data.accounts.filter(a=>a.scope==='directional').map(a=><option key={a.key} value={a.key}>{a.label}</option>)}</optgroup>
    </select></label>}
    {data&&data.accounts.find(a=>a.key===data.account_key)?.scope==='directional'&&<p className="execution-warning">Original directional comparison—not a shared calls + puts account. Its two exit variants still use paired entries and separate balances. Original rules and results are preserved.</p>}
    {error&&<p role="alert">{error}</p>}{!data&&!error&&<p>Loading saved lotto account…</p>}
    {data&&data.status!=='ACTIVE'&&<p>{data.status==='SCHEDULED'?'Scheduled':'Waiting for scanner initialization'} · {formatEasternDateTime(data.scheduled_start)}. No old trades are imported.</p>}
    {data?.status==='ACTIVE'&&<>
      <nav className="workspace-tabs" aria-label="Lotto account sections"><button aria-current={pane==='BALANCE'?'page':undefined} onClick={()=>setPane('BALANCE')}>Balance</button><button aria-current={pane==='TRADES'?'page':undefined} onClick={()=>setPane('TRADES')}>Trades</button></nav>
      {data.unpriced_positions>0&&<p className="execution-warning">{data.unpriced_positions} position(s) have unknown liquidation value. They still consume capital and block further entries in this experiment; closed winners alone are not the account result.</p>}
      {pane==='BALANCE'?<><AccountEquityChart key={data.account_key} account={data}/>
        <section aria-label="Calls versus puts breakdown"><h4>What did calls and puts contribute?</h4>
          <p>Closed-trade net P/L after modeled costs, across the entire selected account. Open and unknown trades are not included in these P/L figures; these are not separate account balances.</p>
          <div className="trade-result-grid">{data.direction_breakdown.map(row=><article className="trade-result-card" key={row.right}>
            <h4>{row.right==='call'?'Calls':'Puts'}</h4><strong>Closed-trade P/L {row.realized_cents<0?'−':'+'}${(Math.abs(row.realized_cents)/100).toFixed(2)}</strong>
            <p>{row.entered} entered · {row.closed} closed · {row.open} open · {row.unpriced} unknown</p>
            <small>{row.pending} waiting for entry · {row.skipped} skipped</small>
          </article>)}</div>
        </section></>:<>
        <TradeResultCards trades={data.trades} onInspect={trade=>trade.tracker_id&&onInspect(trade.tracker_id)}/>
        <nav className="forward-pagination" aria-label="Lotto trade pages"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)}>Previous trades</button><span>Page {data.pagination.page} of {data.pagination.pages}</span><button disabled={page>=data.pagination.pages} onClick={()=>setPage(p=>p+1)}>Next trades</button></nav>
      </>}
      <details><summary>Frozen rules, cash &amp; limitations</summary><p>Targets trigger an exit request; the next verified bid determines the simulated sale. There is no guaranteed 5× fill. The trailing rule arms at 2× the modeled entry premium and requests an exit after a 40% decline from the highest subsequently observed bid. There is no percentage stop before the trail arms. Exit requests cannot use their triggering quote as a fill.</p><p>New entries stop 15 minutes before the exchange close. Remaining positions request exit 5 minutes before close. Missing quotes stay unknown. Settlement is next eligible banking/market day. Quote sizes are unavailable; quotes do not guarantee fills.</p><p>Settled cash ${(data.settled_cents/100).toFixed(2)} · Unsettled ${(data.unsettled_cents/100).toFixed(2)} · Realized ${(data.realized_cents/100).toFixed(2)}</p><pre>{JSON.stringify(data.policy,null,2)}</pre></details>
    </>}
  </section>;
}
