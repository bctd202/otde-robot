import { useEffect, useState } from 'react';
import type { ParlayCandidate } from '../types';
import { formatDateOnly, formatEasternTime, parseApiTimestamp } from '../lib/dates';
import { DirectionBadge } from './DirectionBadge';

const money=(number:number|null|undefined)=>number==null?'—':`$${number.toFixed(2)}`;

export function ParlayTicket({candidate,onPaperEnter,entering=false}:{candidate:ParlayCandidate;onPaperEnter?:(candidate:ParlayCandidate)=>void;entering?:boolean}) {
  const [now,setNow]=useState(()=>Date.now());
  useEffect(()=>{const timer=window.setInterval(()=>setNow(Date.now()),1000);return()=>window.clearInterval(timer)},[]);
  const contract=candidate.contract;
  const validUntil=parseApiTimestamp(candidate.valid_until)?.getTime()??null;
  const secondsRemaining=validUntil==null?null:Math.max(0,Math.ceil((validUntil-now)/1000));
  const lifecycleCurrent=candidate.lifecycle_status==null||(candidate.lifecycle_status==='BUY'&&secondsRemaining!==null&&secondsRemaining>0);
  const verifiedActionable=lifecycleCurrent&&candidate.actionable===true&&contract?.actionable===true&&contract.verification_status==='verified'&&contract.provider==='tradier'&&contract.data_mode==='live'&&Boolean(contract.normalized_symbol)&&Boolean(contract.bid_timestamp)&&Boolean(contract.ask_timestamp)&&Boolean(contract.timestamp);
  const action=candidate.signal_status==='BUY'&&verifiedActionable?'BUY NOW':'WAIT';
  return <article className={`parlay-ticket decision-ticket decision-${candidate.signal_status.toLowerCase()}`}>
    <div className={`strategy-pill ${candidate.strategy_mode==='STRUCTURED_INTRADAY'?'structured':'fast'}`}><b>{candidate.strategy_mode==='STRUCTURED_INTRADAY'?'Structured Intraday':'1-Min / 0DTE'}</b><span>{candidate.timeframe_context} · {candidate.target_dte} · {candidate.strategy_version}</span></div>
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
      {verifiedActionable&&contract?<>
        <strong className="option-symbol">{contract.option_symbol}</strong>
        <dl>
          <div><dt>Expiration</dt><dd>{formatDateOnly(contract.expiration)}</dd></div>
          <div><dt>Strike</dt><dd>{money(contract.strike)}</dd></div>
          <div><dt>Option type</dt><dd>{contract.right.toUpperCase()}</dd></div>
          <div><dt>Current bid</dt><dd>{money(contract.bid)}</dd></div>
          <div><dt>Option ask</dt><dd>{money(contract.ask)}</dd></div>
          <div className="contract-cost"><dt>Estimated contract cost</dt><dd>{money(candidate.contract_cost)}</dd></div>
        </dl>
      </>:<><strong>No verified contract available</strong>{candidate.contract_verification_reason&&<p>{candidate.contract_verification_reason}</p>}</>}
    </section>

    <div className="signal-clock">
      <span><b>Signal timing</b> {candidate.triggered_at?`Triggered ${formatEasternTime(candidate.triggered_at)}`:`Intraday setup generated ${formatEasternTime(candidate.generated_at)}`}</span>
      <span><b>Last verified</b> {formatEasternTime(candidate.last_verified_at||contract?.timestamp||candidate.generated_at)}</span>
      {secondsRemaining!==null&&<span className={secondsRemaining===0?'signal-expired':''}><b>Valid for</b> {secondsRemaining>0?`${Math.floor(secondsRemaining/60)}:${String(secondsRemaining%60).padStart(2,'0')}`:'Expired — awaiting server recheck'}</span>}
      {candidate.validity_reason&&<span><b>Lifecycle</b> {candidate.lifecycle_status} · {candidate.validity_reason}</span>}
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
    {candidate.signal_status==='BUY'&&verifiedActionable&&onPaperEnter&&<button type="button" className="paper-enter" disabled={entering} onClick={()=>onPaperEnter(candidate)}>{entering?'Recording…':'Paper Enter'}</button>}
  </article>;
}
