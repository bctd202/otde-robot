import { useState } from 'react';
import type { DailyWatchResponse } from '../types';

interface Props { data:DailyWatchResponse|null;busy:boolean;message:string;onAdd:(symbol:string)=>void;onRemove:(symbol:string)=>void }

export function DailyWatch({data,busy,message,onAdd,onRemove}:Props) {
  const [symbol,setSymbol]=useState('');
  const symbols=Array.isArray(data?.symbols)?data.symbols:[];
  const available=Math.max(0,(data?.slot_limit??2)-(data?.slots_used??0));
  return <section className="daily-watch" aria-labelledby="daily-watch-title">
    <div><p className="eyebrow">Flex scanner</p><h2 id="daily-watch-title">Watch Today</h2><p>Add up to two ideas for today. They use the same setup and contract rules, then reset next trading day.</p></div>
    <form onSubmit={event=>{event.preventDefault();const value=symbol.trim().toUpperCase();if(value){onAdd(value);setSymbol('')}}}>
      <label htmlFor="daily-watch-symbol">Ticker</label><div><input id="daily-watch-symbol" value={symbol} onChange={event=>setSymbol(event.target.value.toUpperCase())} placeholder="MSTR" maxLength={12} disabled={busy||available===0}/><button type="submit" disabled={busy||available===0||!symbol.trim()}>Add</button></div>
      <small>{available} of {data?.slot_limit??2} slots available</small>
    </form>
    <div className="daily-watch-chips" aria-label="Today's flex symbols">{symbols.length?symbols.map(item=><button key={item} type="button" onClick={()=>onRemove(item)} disabled={busy} aria-label={`Remove ${item}`}>{item}<span aria-hidden="true">×</span></button>):<span>No flex symbols added.</span>}</div>
    {message&&<p className="daily-watch-message" role="status">{message}</p>}
  </section>;
}
