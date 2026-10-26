import {useEffect,useState} from 'react';
import {getLottoPaperTrial} from '../api/client';
import type {LottoTrialResponse,LottoTrialChoice} from '../types';
import {formatEasternDateTime} from '../lib/dates';
import {AccountEquityChart} from './AccountEquityChart';
import {TradeResultCards} from './TradeResultCards';

export function LottoForward({onInspect}:{onInspect:(id:string)=>void}){
  const [data,setData]=useState<LottoTrialResponse|null>(null);
  const [choices,setChoices]=useState<LottoTrialChoice[]>([]);
  const [key,setKey]=useState<string>();
  const [page,setPage]=useState(1);
  const [error,setError]=useState('');
  const [pane,setPane]=useState<'BALANCE'|'TRADES'>('BALANCE');
  const [view,setView]=useState('ENTERED');
  useEffect(()=>{
    let active=true;
    let request=0;
    const load=()=>{const serial=++request;return getLottoPaperTrial(page,key,view).then(result=>{if(!Array.isArray(result.accounts)||!result.accounts.length||!result.accounts.every(a=>a.key&&a.label&&['combined','directional'].includes(a.scope)))throw new Error('Invalid account response');if(active&&serial===request){setData(result);setChoices(result.accounts);setError('')}})
      .catch(()=>{if(active&&serial===request)setError('Lotto account unavailable. Any displayed figures are the last response, not a live balance.')})};
    void load();const timer=window.setInterval(()=>void load(),30000);
    return()=>{active=false;window.clearInterval(timer)};
  },[key,page,view]);
  const choose=(value:string)=>{setKey(value);setPage(1);setData(null);setError('')};
  const selectedKey=key??data?.account_key;
  const isMulti=choices.find(a=>a.key===selectedKey)?.generation==='multi';
  const mainChoices=choices.filter(a=>a.scope==='combined'&&(isMulti?a.generation==='multi':a.generation!=='multi'));
  const otherChoices=choices.filter(a=>!mainChoices.includes(a));
  return <section className="forward-account graph-panel" aria-label="Forward lotto paper accounts">
    <h3>What did the lotto rules actually keep?</h3><p>Two exit-rule experiments: 5× trigger versus a 40% trail after 2×. Each starts with $500 shared by calls and puts. Never add these balances together. No brokerage orders.</p>
    <details className="shared-account-rules"><summary>Shared account limits &amp; modeled costs</summary><p>{isMulti?'New version: up to five simultaneous positions across calls and puts. Maximum $100 premium per standard contract ($1.00 quote), excluding fees and slippage. No daily spending cap. Available settled cash and reserved closing costs still limit purchases.':'Original version: one open idea across calls and puts, $50 all-in entry limit and a combined $100 daily all-in cap.'} One contract per ticker/day. The two exit rules run independently, so later entries can differ. Model: $1.50 opening costs, $0.50 closing costs, plus 1¢ premium slippage each side.</p><p>Cheap contracts can lose their entire premium; multiple positions add to total account exposure.</p></details>
    {choices.length>0&&<><div className="exit-rule-switch" role="group" aria-label="Shared calls and puts exit rule">{mainChoices.map(a=><button key={a.key} type="button" aria-pressed={selectedKey===a.key} onClick={()=>choose(a.key)}><strong>{a.key.includes('fixed5')?'5× Exit':'Trail after 2×'}</strong><span>{a.key.includes('fixed5')?'Request an exit at 5×':'40% trail once doubled'} · Calls + puts · {isMulti?'5 slots':'Original single slot'}</span></button>)}</div>
    <details className="original-experiments"><summary>Other experiment versions</summary><p>Separate research accounts; never add their balances together. Previous policies and history are preserved.</p><label className="account-trial-selector">Experiment version <select value={otherChoices.some(a=>a.key===selectedKey)?selectedKey:''} onChange={e=>choose(e.target.value)}>
      <option value="" disabled>Choose an experiment</option>{otherChoices.map(a=><option key={a.key} value={a.key}>{a.generation==='single'?'Original single slot · ':''}{a.label}</option>)}
    </select></label></details></>}
    {data&&data.accounts.find(a=>a.key===data.account_key)?.scope==='directional'&&<p className="execution-warning">Original directional comparison—not a shared calls + puts account. Its two exit variants still use paired entries and separate balances. Original rules and results are preserved.</p>}
    {error&&<p role="alert">{error}</p>}{!data&&!error&&<p>Loading saved lotto account…</p>}
    {data&&data.status!=='ACTIVE'&&<p>{data.activation_required?'Not activated — requires explicit approval. No funds or trades have been created.':`${data.status==='SCHEDULED'?'Scheduled':'Waiting for scanner initialization'} · ${formatEasternDateTime(data.scheduled_start)}. No old trades are imported.`}</p>}
    {data?.status==='ACTIVE'&&<>
      <nav className="workspace-tabs" aria-label="Lotto account sections"><button aria-current={pane==='BALANCE'?'page':undefined} onClick={()=>setPane('BALANCE')}>Balance</button><button aria-current={pane==='TRADES'?'page':undefined} onClick={()=>setPane('TRADES')}>Trades</button></nav>
      {data.accepting_new_discoveries===false&&<p>Previous experiment: no new discoveries are accepted. Existing positions continue under their original rules.</p>}
      {data.unpriced_positions>0&&<p className="execution-warning">{data.unpriced_positions} position(s) have unknown liquidation value. They still consume capital and position slots; closed winners alone are not the account result.</p>}
      {pane==='BALANCE'?<><AccountEquityChart key={data.account_key} account={data}/>
        <section aria-label="Calls versus puts breakdown"><h4>What did calls and puts contribute?</h4>
          <p>Closed-trade net P/L after modeled costs, across the entire selected account. Open and unknown trades are not included in these P/L figures; these are not separate account balances.</p>
          <div className="trade-result-grid">{data.direction_breakdown.map(row=><article className="trade-result-card" key={row.right}>
            <h4>{row.right==='call'?'Calls':'Puts'}</h4><strong>Closed-trade P/L {row.realized_cents<0?'−':'+'}${(Math.abs(row.realized_cents)/100).toFixed(2)}</strong>
            <p>{row.entered} entered · {row.closed} closed · {row.open} open · {row.unpriced} unknown</p>
            <small>{row.pending} waiting for entry · {row.skipped} skipped</small>
          </article>)}</div>
        </section></>:<>
        <div className="filter-tabs" role="group" aria-label="Lotto trade filter">{[['ENTERED','Entered trades'],['PENDING','Waiting for entry'],['SKIPPED','Skipped opportunities']].map(([value,label])=><button key={value} aria-pressed={view===value} onClick={()=>{if(view!==value){setView(value);setPage(1);setData(null)}}}>{label}</button>)}</div>
        {view!=='ENTERED'&&<p>These opportunities have no simulated fill and are not included as trading gains or losses.</p>}
        {data.trades.length===0?<p>{view==='ENTERED'?'No entered trades in this account yet.':view==='PENDING'?'No entries waiting for a later quote.':'No skipped opportunities in this account.'}</p>:<TradeResultCards trades={data.trades} onInspect={trade=>trade.tracker_id&&onInspect(trade.tracker_id)}/>}
        <nav className="forward-pagination" aria-label="Lotto trade pages"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)}>Previous trades</button><span>Page {data.pagination.page} of {data.pagination.pages}</span><button disabled={page>=data.pagination.pages} onClick={()=>setPage(p=>p+1)}>Next trades</button></nav>
      </>}
      <details><summary>Frozen rules, cash &amp; limitations</summary><p>Targets trigger an exit request; the next verified bid determines the simulated sale. There is no guaranteed 5× fill. The trailing rule arms at 2× the modeled entry premium and requests an exit after a 40% decline from the highest subsequently observed bid. There is no percentage stop before the trail arms. Exit requests cannot use their triggering quote as a fill.</p><p>New entries stop 15 minutes before the exchange close. Remaining positions request exit 5 minutes before close. Missing quotes stay unknown. Settlement is next eligible banking/market day. Quote sizes are unavailable; quotes do not guarantee fills.</p><p>Settled cash ${(data.settled_cents/100).toFixed(2)} · Unsettled ${(data.unsettled_cents/100).toFixed(2)} · Realized ${(data.realized_cents/100).toFixed(2)}</p><pre>{JSON.stringify(data.policy,null,2)}</pre></details>
    </>}
  </section>;
}
