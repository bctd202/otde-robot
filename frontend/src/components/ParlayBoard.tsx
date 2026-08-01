import { useMemo } from 'react';
import type { PaperPosition, ParlayCandidate, ParlayResponse } from '../types';
import { PaperPositions } from './PaperPositions';
import { ParlayTicket } from './ParlayTicket';
import { ProviderStatus } from './ProviderStatus';
import { SignalBadge } from './SignalBadge';
import { StaleDataWarning } from './StaleDataWarning';

export function ParlaySkeleton() {
  return <section className="parlay-skeleton" aria-label="Loading Parlay board"><div /><div /><div /></section>;
}

interface ParlayBoardProps { data:ParlayResponse;updated:Date|null;refreshing:boolean;stale:boolean;onRetry:()=>void;positions?:PaperPosition[];positionsStale?:boolean;onPaperEnter?:(candidate:ParlayCandidate)=>void;onPaperExit?:(position:PaperPosition)=>void;enteringSymbol?:string|null }

export function ParlayBoard({data,updated,refreshing,stale,onRetry,positions=[],positionsStale=false,onPaperEnter,onPaperExit,enteringSymbol}:ParlayBoardProps) {
  const groups=useMemo(()=>({
    ready:data.candidates.filter(item=>item.signal_status==='BUY'),
    waiting:data.candidates.filter(item=>item.signal_status==='WATCH').sort((a,b)=>a.ranking_position-b.ranking_position),
    noTrade:data.candidates.filter(item=>!['BUY','WATCH'].includes(item.signal_status)),
  }),[data.candidates]);
  const scannerHealth=data.scanner_health??{candidate_count:data.candidates.length,unavailable_candidate_count:data.candidates.filter(item=>item.signal_status==='UNAVAILABLE').length,provider_status:data.provider_status.status};
  return <section id="parlay" className="parlay-board" aria-labelledby="parlay-title">
    <header className="parlay-header"><div className="brand-lockup"><img src="/parlay-logo.png" alt="Parlay logo" width="1395" height="446" decoding="async"/><div><p className="eyebrow">Paper 0DTE Decision Board</p><h1 id="parlay-title" className="sr-only">Parlay</h1><p>Disciplined, paper-only market research</p></div></div><ProviderStatus provider={data.provider_status} updated={updated} refreshing={refreshing} onRefresh={onRetry}/></header>
    <div className="board-meta"><p className="paper-notice"><strong>Paper only</strong><span>No live orders are placed.</span></p><p className="freshness" aria-label="Aggregate scanner health">Scanner health: <strong>{scannerHealth.candidate_count} candidates</strong><span>{scannerHealth.unavailable_candidate_count} unavailable</span><span>Provider {scannerHealth.provider_status}</span></p></div>
    {stale&&<StaleDataWarning updated={updated} onRetry={onRetry}/>}

    <section className="decision-section ready-section" aria-labelledby="ready-title"><div className="decision-section-heading"><div><p className="eyebrow">Act now</p><h2 id="ready-title">Ready to Trade</h2></div><span>{groups.ready.length} BUY NOW</span></div>{groups.ready.length===0?<div className="empty-state"><strong>NO QUALIFIED PARLAYS RIGHT NOW</strong><span>Continue scanning. Do not force a trade.</span></div>:<div className="decision-grid">{groups.ready.map(item=><ParlayTicket key={item.symbol} candidate={item} onPaperEnter={onPaperEnter} entering={enteringSymbol===item.symbol}/>)}</div>}</section>

    <section className="decision-section waiting-section" aria-labelledby="waiting-title"><div className="decision-section-heading"><div><p className="eyebrow">Approaching a trigger</p><h2 id="waiting-title">Waiting Room</h2></div><span>{groups.waiting.length} WAIT</span></div><p className="section-note">Ordered by the scanner's existing readiness rank.</p>{groups.waiting.length===0?<p className="section-empty">No setups are waiting for a trigger.</p>:<div className="decision-grid">{groups.waiting.map(item=><ParlayTicket key={item.symbol} candidate={item}/>)}</div>}</section>

    <details className="no-trade-section"><summary><span><b>No Trade</b><small>MISSED, PASS, and unavailable setups</small></span><strong>{groups.noTrade.length}</strong></summary><div className="no-trade-list">{groups.noTrade.map(item=><details key={item.symbol} className="no-trade-row"><summary><b>#{item.ranking_position} {item.symbol}</b><SignalBadge status={item.signal_status}/><span>{item.direction==='none'?'No contract':item.direction.toUpperCase()}</span></summary><div><p>{item.primary_action}</p>{item.unavailable_reason&&<p>{item.unavailable_reason}</p>}<p><b>Score:</b> {item.score.toFixed(1)} · {item.score_label}</p><p><b>Data freshness:</b> {item.data_freshness.replaceAll('_',' ')}</p>{item.rejection_reasons.length>0&&<ul>{item.rejection_reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}</div></details>)}</div></details>

    <PaperPositions positions={positions} stale={positionsStale} onExit={position=>onPaperExit?.(position)}/>
  </section>;
}
