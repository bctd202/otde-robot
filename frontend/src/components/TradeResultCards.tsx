import {useState} from 'react';
import type {MoneyTrade} from '../types';
import {formatEasternDateTime} from '../lib/dates';

const money=(value:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value/100);
function contractLabel(symbol:string){
  const match=symbol.replaceAll(' ','').match(/^([A-Z0-9.]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/);
  return match?`${match[1]} ${match[5]==='C'?'CALL':'PUT'} $${Number(match[6])/1000} · ${match[3]}/${match[4]}/20${match[2]}`:symbol;
}
export function tradeOutcome(trade:MoneyTrade){
  const closed=['CLOSED','UNSETTLED'].includes(trade.status);
  const proceeds=closed?trade.net_proceeds_cents:trade.status==='OPEN'?trade.estimated_net_proceeds_cents:null;
  const cost=trade.entry_debit_cents;
  if(proceeds==null||cost==null||cost<=0)return null;
  return {closed,proceeds,pnl:proceeds-cost,percent:(proceeds/cost-1)*100,multiple:proceeds/cost};
}

export function TradeResultCards({trades,onInspect}:{trades:MoneyTrade[];onInspect?:(trade:MoneyTrade)=>void}){
  const [unit,setUnit]=useState<'PERCENT'|'MULTIPLE'>('PERCENT');
  return <section aria-label="Paper trade outcomes"><div className="equity-controls" role="group" aria-label="Trade result display">
    <button aria-pressed={unit==='PERCENT'} onClick={()=>setUnit('PERCENT')}>Gain / loss %</button>
    <button aria-pressed={unit==='MULTIPLE'} onClick={()=>setUnit('MULTIPLE')}>Money back ×</button>
  </div><p>Option-trade results after modeled costs—not stock movement or account return. These are simulated trades, not broker fills.</p>
  {trades.length===0?<p>No paper trades yet. No historical trades are imported.</p>:<div className="trade-result-grid">{trades.map(trade=>{
    const result=tradeOutcome(trade);
    const label=trade.status==='SKIPPED'?'Not entered':trade.status==='PENDING_ENTRY'?'Waiting for entry':result?.closed?'Closed':trade.status==='UNPRICED'?'Exit unknown':'Open · estimated';
    return <article className="trade-result-card" key={trade.id}><header><strong>{contractLabel(trade.option_symbol)}</strong><span>{label} · Paper</span></header>
      <div className="trade-cash-flow"><span>Cost incl. fees<strong>{trade.entry_debit_cents==null?'Not spent':money(trade.entry_debit_cents)}</strong></span><span aria-hidden="true">→</span><span>{result?.closed?'Net proceeds':trade.status==='OPEN'?'Estimated net sale value':'Proceeds'}<strong>{result?money(result.proceeds):trade.entry_debit_cents==null?'—':'Unknown'}</strong></span></div>
      <h4 className={result?(result.pnl>=0?'positive-text':'negative-text'):''}>{result?`${result.closed?'':'Estimated '}${result.pnl>=0?'gain':'loss'} ${money(Math.abs(result.pnl))} · ${unit==='PERCENT'?`${result.percent>0?'+':''}${result.percent.toFixed(1)}%`:`${result.multiple.toFixed(2)}× returned`}`:trade.status==='SKIPPED'||trade.status==='PENDING_ENTRY'?'No trade result':'Result unknown — missing price evidence'}</h4>
      {trade.exit_reason&&<p>Exit: {trade.exit_reason.replaceAll('_',' ').toLowerCase()}</p>}{trade.reason&&<p>{trade.reason}</p>}
      {trade.entry_at&&<small>Entered {formatEasternDateTime(trade.entry_at)}{trade.exit_at?` · Exited ${formatEasternDateTime(trade.exit_at)}`:''}</small>}
      {trade.status==='OPEN'&&trade.valuation?.bid_at&&<p>Bid observed {formatEasternDateTime(trade.valuation.bid_at)}. Not a completed sale.</p>}
      {onInspect&&<button onClick={()=>onInspect(trade)}>Inspect quote path</button>}
      <details><summary>Trade evidence &amp; assumptions</summary><p>Percentage = net profit ÷ total entry debit. Multiple = net proceeds ÷ total entry debit. A 2× return means +100%, not +200%.</p><pre>{JSON.stringify(trade,null,2)}</pre></details>
    </article>;
  })}</div>}</section>;
}
