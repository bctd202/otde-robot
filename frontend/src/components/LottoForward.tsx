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
    const load=()=>getLottoPaperTrial(page,key).then(result=>{if(!Array.isArray(result.accounts)||result.accounts.length!==4)throw new Error('Invalid account response');if(active){setData(result);setError('')}})
      .catch(()=>{if(active)setError('Lotto account unavailable. Any displayed figures are the last response, not a live balance.')});
    void load();const timer=window.setInterval(()=>void load(),30000);
    return()=>{active=false;window.clearInterval(timer)};
  },[key,page]);
  return <section className="forward-account graph-panel" aria-label="Forward lotto paper accounts">
    <h3>What did the lotto rules actually keep?</h3><p>Four separate $500 paper experiments. Never add these balances together. CALL is the corrected bullish baseline; PUT is a separate bearish experiment. No brokerage orders.</p>
    <p>The two exits share entry decisions. One contract per ticker/day; one open idea per direction; $100 daily all-in cap. Model: $1.50 opening costs, $0.50 closing costs, plus 1¢ premium slippage each side.</p>
    {data&&<label className="account-trial-selector">Lotto experiment <select value={key??data.accounts[0].key} onChange={e=>{setKey(e.target.value);setPage(1);setData(null);setError('')}}>{data.accounts.map(a=><option key={a.key} value={a.key}>{a.label}</option>)}</select></label>}
    {error&&<p role="alert">{error}</p>}{!data&&!error&&<p>Loading saved lotto account…</p>}
    {data&&data.status!=='ACTIVE'&&<p>{data.status==='SCHEDULED'?'Scheduled':'Waiting for scanner initialization'} · {formatEasternDateTime(data.scheduled_start)}. No old trades are imported.</p>}
    {data?.status==='ACTIVE'&&<>
      <nav className="workspace-tabs" aria-label="Lotto account sections"><button aria-current={pane==='BALANCE'?'page':undefined} onClick={()=>setPane('BALANCE')}>Balance</button><button aria-current={pane==='TRADES'?'page':undefined} onClick={()=>setPane('TRADES')}>Trades</button></nav>
      {data.unpriced_positions>0&&<p className="execution-warning">{data.unpriced_positions} position(s) have unknown liquidation value. They still consume capital and block further paired entries; closed winners alone are not the account result.</p>}
      {pane==='BALANCE'?<AccountEquityChart key={data.account_key} account={data}/>:<>
        <TradeResultCards trades={data.trades} onInspect={trade=>trade.tracker_id&&onInspect(trade.tracker_id)}/>
        <nav className="forward-pagination" aria-label="Lotto trade pages"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)}>Previous trades</button><span>Page {data.pagination.page} of {data.pagination.pages}</span><button disabled={page>=data.pagination.pages} onClick={()=>setPage(p=>p+1)}>Next trades</button></nav>
      </>}
      <details><summary>Frozen rules, cash &amp; limitations</summary><p>Targets trigger an exit request; the next verified bid determines the simulated sale. There is no guaranteed 5× fill. The trailing rule arms at 2× the modeled entry premium and requests an exit after a 40% decline from the highest subsequently observed bid. Exit requests cannot use their triggering quote as a fill.</p><p>New entries stop 15 minutes before the exchange close. Remaining positions request exit 5 minutes before close. Missing quotes stay unknown. Settlement is next eligible banking/market day. Quote sizes are unavailable; quotes do not guarantee fills.</p><p>Settled cash ${(data.settled_cents/100).toFixed(2)} · Unsettled ${(data.unsettled_cents/100).toFixed(2)} · Realized ${(data.realized_cents/100).toFixed(2)}</p><pre>{JSON.stringify(data.policy,null,2)}</pre></details>
    </>}
  </section>;
}
