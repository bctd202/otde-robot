import {useEffect,useState} from 'react';
import {getEntryCapReview} from '../api/client';
import {formatEasternDateTime} from '../lib/dates';
import './entry-cap-review.css';

type Comparison={cap_cents:number;eligible:number;priced:number;positive:number;negative:number;
  flat:number;gaps:number;pending:number;average_net_cents:number|null;complete_quote_evidence:boolean};
type ReviewRow={id:number;at:string;ticker:string;right:string;strike:number;expiration:string;
  option_symbol:string;cap_only:boolean;all_in_cents:number;source_cap_cents:number;entry_ask:number;
  status:'PRICED'|'GAP'|'PENDING'|'NOT_ELIGIBLE';net_pnl_cents:number|null;reason:string|null;
  entry_quote:Record<string,unknown>;exit_quote:Record<string,unknown>|null};
export type EntryCapReviewData={current_cap_cents:number|null;legacy_without_entry_receipt:number;
  recorded_skips:number;window_records:number;window_truncated:boolean;cap_only_records:number;
  comparisons:Comparison[];rows:ReviewRow[];page:number;pages:number;limitation:string};
const money=(c:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(c/100);

export function EntryCapReview({active=false}:{active?:boolean}){
  const [open,setOpen]=useState(()=>new URLSearchParams(window.location.search).get('review_caps')==='1');
  const [page,setPage]=useState(1),[data,setData]=useState<EntryCapReviewData|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    if(!active||!open)return;
    let current=true;
    const load=()=>getEntryCapReview(page).then(result=>{if(current){setData(result);setError('')}})
      .catch(()=>{if(current)setError('Price-limit review unavailable. Any figures below are the last saved response.')});
    void load();const timer=window.setInterval(()=>void load(),30000);
    return()=>{current=false;window.clearInterval(timer)};
  },[active,open,page]);
  return <details className="entry-cap-review graph-panel" open={open} onToggle={e=>setOpen(e.currentTarget.open)}>
    <summary>Would a higher entry limit help? <span>Read-only research</span></summary>
    <section aria-label="Entry-price limit review">
      <h3>Main account · skipped-price review</h3>
      <p><strong>{data?.current_cap_cents!=null?`Current all-in entry cap: ${money(data.current_cap_cents)} · unchanged`:'Account limits stay unchanged.'}</strong></p>
      <p>$125 and $150 below are comparison scenarios. These opportunities were not entered; no additional account or money is created.</p>
      {error&&<p role="alert">{error}</p>}
      {!data&&!error&&<p>Loading saved price-limit evidence…</p>}
      {data&&<>
        <p>{data.recorded_skips} new price-limit receipts · {data.cap_only_records} passed the other entry checks at that moment.</p>
        {data.legacy_without_entry_receipt>0&&<p className="cap-review-gap">{data.legacy_without_entry_receipt} older price-limit skips lack the exact rejection-quote receipt. They remain preserved and are excluded from this comparison.</p>}
        {data.recorded_skips===0&&<p>Collection starts with the next price-limit rejection after installation. Older quote samples are not turned into hypothetical fills.</p>}
        {data.window_truncated&&<p>Showing the latest {data.window_records} receipts; earlier records remain saved.</p>}
        <div className="cap-review-grid">{data.comparisons.map(c=>{
          const unknown=c.pending+c.gaps;
          return <article key={c.cap_cents} className="cap-review-scenario">
            <h4>{money(c.cap_cents)} ceiling · scenario only</h4>
            <p><strong>{c.eligible}</strong> extra eligible opportunities · {c.priced} with entry and exit evidence</p>
            {c.eligible>0?<div className="cap-review-bar" role="img" aria-label={`${money(c.cap_cents)} scenario: ${c.positive} positive, ${c.negative} negative, ${c.flat} flat, ${unknown} open or missing outcomes`}>
              {[['positive',c.positive],['negative',c.negative],['flat',c.flat],['unknown',unknown]].map(([label,n])=>
                <span key={label} className={`cap-review-${label}`} style={{width:`${Number(n)/c.eligible*100}%`}}/>)}</div>:<p>No eligible prospective examples yet.</p>}
            <p>{c.positive} positive · {c.negative} negative · {c.flat} flat · {unknown} open or missing</p>
            <strong>Average modeled P/L per priced opportunity: {c.average_net_cents===null?'Not enough quote evidence':money(c.average_net_cents)}</strong>
            <p>{c.pending} still awaiting outcome · {c.gaps} missing exit evidence</p>
            {!c.complete_quote_evidence&&<small>Incomplete evidence. Missing outcomes are not counted as $0.</small>}
          </article>;
        })}</div>
        <p>{data.limitation}</p>
        <p>These bars count outcomes; they are not account-value or portfolio-return graphs. The averages describe only priced examples, not an expected return or a recommendation to raise the cap.</p>
        <h4>Opportunity receipts · not executed trades</h4>
        {data.rows.map(r=><article key={r.id} className="cap-review-receipt">
          <strong>{r.ticker} {r.right.toUpperCase()} ${r.strike} · expires {r.expiration}</strong>
          <p>{formatEasternDateTime(r.at)} · hypothetical entry cost and reserve {money(r.all_in_cents)}</p>
          <p>{!r.cap_only?'Also blocked by cash or available slots':r.status==='NOT_ELIGIBLE'?'Above both comparison ceilings':r.status==='PRICED'?`Modeled outcome after costs: ${money(r.net_pnl_cents!)}`:r.status==='GAP'?'Outcome unpriced':'Awaiting the original strategy exit and later quote'}</p>
          {r.reason&&<small>{r.reason}</small>}
          <details><summary>Inspect saved quote receipts</summary><pre>{JSON.stringify({entry:r.entry_quote,exit:r.exit_quote},null,2)}</pre></details>
        </article>)}
        <nav aria-label="Price-limit review pages"><button disabled={data.page===1} onClick={()=>setPage(data.page-1)}>Previous</button><span>Page {data.page} of {data.pages}</span><button disabled={data.page===data.pages} onClick={()=>setPage(data.page+1)}>Next</button></nav>
      </>}
    </section>
  </details>;
}
