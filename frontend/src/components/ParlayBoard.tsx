import { useMemo, useState } from 'react';
import type { PaperPosition, ParlayCandidate, ParlayResponse } from '../types';
import { ParlayScannerTable } from './ParlayScannerTable';
import { ParlayTicket } from './ParlayTicket';
import { ProviderStatus } from './ProviderStatus';
import { matches, ScannerFilters, type Filter } from './ScannerFilters';
import { StaleDataWarning } from './StaleDataWarning';
import { PaperPositions } from './PaperPositions';
export function ParlaySkeleton(){return <section className="parlay-skeleton" aria-label="Loading Parlay board"><div/><div/><div/></section>}
export function ParlayBoard({data,updated,refreshing,stale,onRetry,positions=[],positionsStale=false,onPaperEnter,onPaperExit,enteringSymbol}:{data:ParlayResponse;updated:Date|null;refreshing:boolean;stale:boolean;onRetry:()=>void;positions?:PaperPosition[];positionsStale?:boolean;onPaperEnter?:(candidate:ParlayCandidate)=>void;onPaperExit?:(position:PaperPosition)=>void;enteringSymbol?:string|null}) { const [filter,setFilter]=useState<Filter>('ALL'); const shown=useMemo(()=>data.candidates.filter(candidate=>matches(candidate,filter)),[data.candidates,filter]); const qualified=data.candidates.filter(candidate=>candidate.signal_status==='BUY'||candidate.signal_status==='WATCH'); const hero=qualified[0]; return <section id="parlay" className="parlay-board">
  <header className="parlay-header"><div><p className="eyebrow">PARLAY</p><h1>Parlay</h1><p>Paper-only 0DTE research</p></div><ProviderStatus provider={data.provider_status} updated={updated} refreshing={refreshing}/></header>
  <p className="paper-notice">Paper-only research. No live orders are placed.</p>{stale&&<StaleDataWarning updated={updated} onRetry={onRetry}/>}<p className="freshness">Data freshness: {data.candidates[0]?.data_freshness??data.provider_status.status}</p>
  {!hero&&<div className="empty-state"><strong>NO QUALIFIED PARLAYS RIGHT NOW</strong><span>Continue scanning. Do not force a trade.</span></div>}
  {hero&&<ParlayTicket candidate={hero} hero onPaperEnter={onPaperEnter} entering={enteringSymbol===hero.symbol}/>}<div className="supporting-tickets">{qualified.slice(1,3).map(candidate=><ParlayTicket candidate={candidate} key={candidate.symbol} onPaperEnter={onPaperEnter} entering={enteringSymbol===candidate.symbol}/>)}</div>
  <PaperPositions positions={positions} stale={positionsStale} onExit={position=>onPaperExit?.(position)}/>
  <div className="scanner-heading"><div><p className="eyebrow">FULL UNIVERSE</p><h2>12-symbol scanner board</h2></div><span>{shown.length} shown</span></div><ScannerFilters candidates={data.candidates} active={filter} onChange={setFilter}/><ParlayScannerTable candidates={shown}/>
</section>; }
