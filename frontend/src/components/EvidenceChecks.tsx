import type {CollectionEvidence,ShadowEvidenceAudit} from '../types';
import {formatEasternDateTime} from '../lib/dates';
import './evidence-checks.css';

const dollars=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'});
const collectionLabels={CURRENT:'Recent evaluation saved',STALE:'Scanner data overdue',CLOSED:'Scanner sleeping · market closed',HELD:'Scanner held by operator',WARMING_UP:'Waiting for opening scans'};

export function CollectionChecks({evidence}:{evidence?:CollectionEvidence}){
  if(!evidence)return null;
  return <details className="collection-checks">
    <summary className={evidence.status==='STALE'||evidence.has_coverage_gaps?'evidence-warning':''}>
      {collectionLabels[evidence.status]}{evidence.has_coverage_gaps?' · Coverage gaps — review':''}
    </summary>
    <div className="collection-details"><strong>Last five trading sessions</strong><p>{evidence.basis} Closed hours are not missing scans. A connected server is not proof of collection.</p>
      {evidence.sessions.map(day=><div className="coverage-day" key={day.date}><span>{day.date}{!day.complete_session?' · so far':''}</span>
        <meter min="0" max={Math.max(1,day.expected_minutes)} value={day.observed_minutes} aria-label={`${day.date} saved evaluation minutes`}/>
        <span>{day.observed_minutes}/{day.expected_minutes} minutes · {day.coverage_percent??'—'}%</span></div>)}
      {evidence.sessions.some(d=>d.input_coverage?.length)&&<details><summary>Actual candle coverage by ticker</summary>
        {evidence.sessions.filter(d=>d.input_coverage?.length).map(d=><div key={d.date}><h4>{d.date}</h4>
          <p>Measured since {formatEasternDateTime(d.input_evidence_started_at)}. {d.input_basis}</p>
          <ul>{d.input_coverage?.map(s=><li key={s.symbol}>{s.symbol}: {s.valid_minutes}/{s.expected_minutes} valid minute inputs</li>)}</ul></div>)}
      </details>}
      {evidence.scan_timing&&<details><summary>Scan speed &amp; bottlenecks</summary>
        {evidence.scan_timing.measured_scans?<>
          <p>{evidence.scan_timing.measured_scans} measured scans · 95% finished within {evidence.scan_timing.p95_seconds}s · {evidence.scan_timing.over_minute_scans} took at least a minute.</p>
          <p>Latest measured run: {formatEasternDateTime(evidence.scan_timing.latest_at)}</p>
          <ul>{Object.entries(evidence.scan_timing.latest_phases_ms).map(([phase,ms])=><li key={phase}>{phase.replaceAll('_',' ')}: {(ms/1000).toFixed(1)}s</li>)}</ul>
        </>:<p>No measured scans yet. Timing starts with the new collector; historical gaps remain visible.</p>}
        <p>{evidence.scan_timing.basis}</p>
      </details>}
    </div>
  </details>;
}

export function ShadowEvidenceChecks({audit}:{audit?:ShadowEvidenceAudit}){
  if(!audit)return null;
  const scale=Math.max(1,...audit.daily.map(day=>Math.abs(day.pnl_dollars)));
  return <section className="shadow-evidence" aria-label="Option evidence checks">
    <h3>How much depends on one good day?</h3>
    {!audit.quoted_trades?<p>No quoted exits to audit yet.</p>:<>
      <div className="evidence-numbers"><div><span>Best entry day · {audit.best_entry_day}</span><strong>{dollars.format(audit.best_day_pnl_dollars??0)}</strong></div>
        <div><span>All other days combined</span><strong>{dollars.format(audit.without_best_day_pnl_dollars??0)}</strong></div>
        <div><span>Trades with review flags</span><strong>{audit.flagged_trades} / {audit.quoted_trades}</strong></div></div>
      <p>Gross option quotes, not cash-account returns. Removing the best day here is a sensitivity check—not a revised result. All trades remain in the totals.</p>
      <details><summary>Daily contributions & timing review</summary>
        <div className="evidence-bars">{audit.daily.map(day=><div key={day.date}><span>{day.date}</span><div className="evidence-bar-track"><i className={day.pnl_dollars<0?'negative':''} style={{width:`${Math.abs(day.pnl_dollars)/scale*100}%`}}/></div><span>{dollars.format(day.pnl_dollars)}</span></div>)}</div>
        <p>{audit.basis}</p><p>Up to 10 flagged examples, largest absolute dollar result first. Flags mean review—not confirmed errors.</p>
        {audit.flagged_examples.map(row=><details key={row.signal_id}><summary>{row.ticker} · {row.date} · {dollars.format(row.pnl_dollars)}</summary>
          <ul>{row.flags.map(flag=><li key={flag}>{flag.toLowerCase().replaceAll('_',' ')}</li>)}</ul>
          <p>Entry quote: {formatEasternDateTime(row.entry_quote_at)} · recorded observation: {formatEasternDateTime(row.entry_observed_at)}</p>
          <p>Exit quote: {formatEasternDateTime(row.exit_quote_at)} · recorded observation: {formatEasternDateTime(row.exit_observed_at)} · exit lag: {row.quote_lag_seconds??'unknown'} seconds.</p>
        </details>)}
      </details>
    </>}
  </section>;
}
