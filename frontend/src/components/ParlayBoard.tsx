import { useMemo } from 'react';
import type { PaperPosition, ParlayCandidate, ParlayResponse, StrategyView } from '../types';
import { PaperPositions } from './PaperPositions';
import { ParlayTicket } from './ParlayTicket';
import { ProviderStatus } from './ProviderStatus';
import { SignalBadge } from './SignalBadge';
import { StaleDataWarning } from './StaleDataWarning';

export function ParlaySkeleton() {
  return <section className="parlay-skeleton" aria-label="Loading Parlay board"><div /><div /><div /></section>;
}

interface ParlayBoardProps { data:ParlayResponse;selectedStrategy?:StrategyView;updated:Date|null;refreshing:boolean;stale:boolean;onRetry:()=>void;positions?:PaperPosition[];positionsStale?:boolean;onPaperEnter?:(candidate:ParlayCandidate)=>void;onPaperExit?:(position:PaperPosition)=>void;enteringSymbol?:string|null }

const lifecycleIsCurrent=(item:ParlayCandidate)=>item.lifecycle_status==null||(['BUY','WATCH'].includes(item.lifecycle_status)&&item.lifecycle_status===item.signal_status&&Boolean(item.valid_until)&&Date.parse(item.valid_until!)>Date.now());
const isVerifiedActionable=(item:ParlayCandidate)=>item.signal_status==='BUY'&&lifecycleIsCurrent(item)&&item.actionable===true&&item.contract?.actionable===true&&item.contract.verification_status==='verified'&&item.contract.provider==='tradier'&&item.contract.data_mode==='live'&&Boolean(item.contract.normalized_symbol)&&Boolean(item.contract.bid_timestamp)&&Boolean(item.contract.ask_timestamp)&&Boolean(item.contract.timestamp);

export function ParlayBoard({data,selectedStrategy='ALL',updated,refreshing,stale,onRetry,positions=[],positionsStale=false,onPaperEnter,onPaperExit,enteringSymbol}:ParlayBoardProps) {
  const visible=useMemo(()=>data.candidates.filter(item=>selectedStrategy==='ALL'||item.strategy_mode===selectedStrategy),[data.candidates,selectedStrategy]);
  const groups=useMemo(()=>({
    ready:visible.filter(isVerifiedActionable),
    waiting:visible.filter(item=>item.signal_status==='WATCH'&&lifecycleIsCurrent(item)).sort((a,b)=>a.ranking_position-b.ranking_position),
    noTrade:visible.filter(item=>!isVerifiedActionable(item)&&!(item.signal_status==='WATCH'&&lifecycleIsCurrent(item))),
  }),[visible]);
  const scannerHealth=data.scanner_health??{candidate_count:data.candidates.length,unavailable_candidate_count:data.candidates.filter(item=>item.signal_status==='UNAVAILABLE').length,provider_status:data.provider_status.status};
  return <section id="parlay" className="parlay-board" aria-labelledby="parlay-title">
    <header className="parlay-header"><div className="brand-lockup"><img src="/parlay-logo.png" alt="Parlay logo" width="1395" height="446" decoding="async"/><div><p className="eyebrow">Paper Dual-Strategy Decision Board</p><h1 id="parlay-title" className="sr-only">Parlay</h1><p>Disciplined, paper-only market research</p></div></div><ProviderStatus provider={data.provider_status} updated={updated} refreshing={refreshing} onRefresh={onRetry}/></header>
    <div className="board-meta"><p className="paper-notice"><strong>Paper only</strong><span>No live orders are placed.</span></p><p className="freshness" aria-label="Aggregate scanner health">Scanner health: <strong>{visible.length} shown / {scannerHealth.candidate_count} tracked</strong><span>{scannerHealth.unavailable_candidate_count} unavailable</span><span>Provider {scannerHealth.provider_status}</span><span>Engine {scannerHealth.engine_status??'unknown'}</span>{scannerHealth.api_budget?.remaining!=null&&<span className={scannerHealth.api_budget.remaining<=20?'budget-low':''}>API budget {scannerHealth.api_budget.remaining}/{scannerHealth.api_budget.safety_limit}</span>}{scannerHealth.evaluation_candle_at&&<span>Completed candle {new Date(scannerHealth.evaluation_candle_at).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York'})} ET</span>}</p></div>
    {stale&&<StaleDataWarning updated={updated} onRetry={onRetry}/>}

    <section className="decision-section ready-section" aria-labelledby="ready-title"><div className="decision-section-heading"><div><p className="eyebrow">Act now</p><h2 id="ready-title">Ready to Trade</h2></div><span>{groups.ready.length} BUY NOW</span></div>{groups.ready.length===0?<div className="empty-state"><strong>NO QUALIFIED PARLAYS RIGHT NOW</strong><span>Continue scanning. Do not force a trade.</span></div>:<div className="decision-grid">{groups.ready.map(item=><ParlayTicket key={`${item.strategy_mode}:${item.symbol}`} candidate={item} onPaperEnter={onPaperEnter} entering={enteringSymbol===`${item.strategy_mode}:${item.symbol}`}/>)}</div>}</section>

    <section className="decision-section waiting-section" aria-labelledby="waiting-title"><div className="decision-section-heading"><div><p className="eyebrow">Approaching a trigger</p><h2 id="waiting-title">Waiting Room</h2></div><span>{groups.waiting.length} WAIT</span></div><p className="section-note">Ordered by each strategy&apos;s readiness rank.</p>{groups.waiting.length===0?<p className="section-empty">No setups are waiting for a trigger.</p>:<div className="decision-grid">{groups.waiting.map(item=><ParlayTicket key={`${item.strategy_mode}:${item.symbol}`} candidate={item}/>)}</div>}</section>

    <details className="no-trade-section"><summary><span><b>No Trade</b><small>Expired, missed, pass, and unavailable setups</small></span><strong>{groups.noTrade.length}</strong></summary><div className="no-trade-list">{groups.noTrade.map(item=><details key={`${item.strategy_mode}:${item.symbol}`} className="no-trade-row"><summary><b>#{item.ranking_position} {item.symbol}</b><SignalBadge status={item.signal_status}/><span>{item.strategy_mode==='STRUCTURED_INTRADAY'?'STRUCTURED':'1-MIN'}</span><span>{item.direction==='none'?'No contract':item.direction.toUpperCase()}</span></summary><div><p>{item.primary_action}</p><p><b>Strategy:</b> {item.strategy_mode==='STRUCTURED_INTRADAY'?'Structured Intraday':'1-Min / 0DTE'} · {item.strategy_version}</p>{item.validity_reason&&<p><b>Lifecycle:</b> {item.lifecycle_status} — {item.validity_reason}</p>}{item.unavailable_reason&&<p>{item.unavailable_reason}</p>}<p><b>Score:</b> {item.score.toFixed(1)} · {item.score_label}</p><p><b>Data freshness:</b> {item.data_freshness.replaceAll('_',' ')}</p>{item.underlying_trigger!==null&&<p><b>Underlying trigger:</b> {item.underlying_trigger.toFixed(2)}</p>}{item.underlying_invalidation!==null&&<p><b>Underlying invalidation:</b> {item.underlying_invalidation.toFixed(2)}</p>}{item.first_underlying_target!==null&&<p><b>Underlying target:</b> {item.first_underlying_target.toFixed(2)}</p>}{item.contract_verification_reason&&<p><b>Contract:</b> No verified contract available — {item.contract_verification_reason}</p>}{item.rejection_reasons.length>0&&<ul>{item.rejection_reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}</div></details>)}</div></details>

    <PaperPositions positions={positions} stale={positionsStale} onExit={position=>onPaperExit?.(position)}/>
  </section>;
}
