import type { ParlayCandidate } from '../types';
import { formatDateOnly, formatEasternTime } from '../lib/dates';
import { DirectionBadge } from './DirectionBadge';

const money=(number:number|null|undefined)=>number==null?'—':`$${number.toFixed(2)}`;

export function ParlayTicket({candidate,onPaperEnter,entering=false}:{candidate:ParlayCandidate;onPaperEnter?:(candidate:ParlayCandidate)=>void;entering?:boolean}) {
  const action=candidate.actionable&&candidate.signal_status==='BUY'?'BUY NOW':candidate.data_mode==='mock'?'DEMO DATA':'NOT ACTIONABLE';
  const contract=candidate.contract;
  return <article className={`parlay-ticket decision-ticket decision-${candidate.signal_status.toLowerCase()}`}>
    <header className="decision-header">
      <div><span className="ranking">#{candidate.ranking_position}</span><h3>{candidate.symbol}</h3></div>
      <DirectionBadge direction={candidate.direction}/>
      <strong className="decision-action">{action}</strong>
    </header>

    <div className="decision-prices">
      <div><span>Current underlying price</span><strong>{money(candidate.underlying_price)}</strong></div>
      <div><span>Underlying entry</span><strong>{money(candidate.underlying_trigger)}</strong></div>
      <div className="risk"><span>Underlying stop</span><strong>{money(candidate.underlying_invalidation)}</strong></div>
      <div><span>Underlying target</span><strong>{money(candidate.first_underlying_target)}</strong></div>
    </div>

    <section className="contract-block" aria-label={`${candidate.symbol} exact option contract`}>
      <p>Exact option contract</p>
      {contract?<>
        <span className={`verification ${candidate.verification_status}`}>{candidate.verification_status==='verified'?'TRADIER VERIFIED':candidate.data_mode==='mock'?'DEMO DATA':'UNVERIFIED'}</span>
        <strong className="option-symbol">{contract.option_symbol}</strong>
        <dl>
          <div><dt>Expiration</dt><dd>{formatDateOnly(contract.expiration)}</dd></div>
          <div><dt>Strike</dt><dd>{money(contract.strike)}</dd></div>
          <div><dt>Option type</dt><dd>{contract.right.toUpperCase()}</dd></div>
          <div><dt>Current bid</dt><dd>{money(contract.bid)}</dd></div>
          <div><dt>Option ask</dt><dd>{money(contract.ask)}</dd></div>
          <div className="contract-cost"><dt>Estimated contract cost</dt><dd>{money(candidate.contract_cost)}</dd></div>
          <div><dt>Provider / mode</dt><dd>{candidate.provider} · {candidate.data_mode}</dd></div>
          <div><dt>Quote status</dt><dd>{candidate.quote_freshness} · {formatEasternTime(contract.timestamp)}</dd></div>
        </dl>
        {!candidate.actionable&&<p><strong>No verified contract available</strong> — {candidate.verification_reason}</p>}
      </>:<strong>Contract unavailable — wait for complete data</strong>}
    </section>

    <div className="signal-clock">
      <span><b>Signal timing</b> Intraday setup generated {formatEasternTime(candidate.generated_at)}</span>
      <span><b>Last updated</b> {formatEasternTime(contract?.timestamp||candidate.generated_at)}</span>
    </div>

    <details className="setup-explanation">
      <summary>Why this setup?</summary>
      <div className="diagnostic-grid">
        <p><span>Score</span><strong>{candidate.score.toFixed(1)} · {candidate.score_label}</strong></p>
        <p><span>Technical action</span><strong>{candidate.primary_action}</strong></p>
        <p><span>Data freshness</span><strong>{candidate.data_freshness.replaceAll('_',' ')}</strong></p>
        <p><span>Entry range</span><strong>{money(candidate.entry_low)}–{money(candidate.entry_high)}</strong></p>
        <p><span>No-chase level</span><strong>{money(candidate.no_chase_price)}</strong></p>
        <p><span>Stretch target</span><strong>{money(candidate.stretch_underlying_target)}</strong></p>
      </div>
      {candidate.reasons.length>0&&<ul>{candidate.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}
      {candidate.rejection_reasons.length>0&&<ul className="rejection-list">{candidate.rejection_reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}
    </details>
    {candidate.signal_status==='BUY'&&contract&&onPaperEnter&&<button type="button" className="paper-enter" disabled={entering||!candidate.actionable} onClick={()=>onPaperEnter(candidate)}>{candidate.actionable?(entering?'Recording…':'Paper Enter'):'Paper entry disabled — unverified data'}</button>}
  </article>;
}
