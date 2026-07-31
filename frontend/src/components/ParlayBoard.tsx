import { useMemo, useState } from 'react';
import type { PaperPosition, ParlayCandidate, ParlayResponse } from '../types';
import { PaperPositions } from './PaperPositions';
import { ParlayScannerTable } from './ParlayScannerTable';
import { ParlayTicket } from './ParlayTicket';
import { ProviderStatus } from './ProviderStatus';
import { matches, ScannerFilters, type Filter } from './ScannerFilters';
import { StaleDataWarning } from './StaleDataWarning';

export function ParlaySkeleton() {
  return <section className="parlay-skeleton" aria-label="Loading Parlay board"><div /><div /><div /></section>;
}

interface ParlayBoardProps {
  data: ParlayResponse;
  updated: Date | null;
  refreshing: boolean;
  stale: boolean;
  onRetry: () => void;
  positions?: PaperPosition[];
  positionsStale?: boolean;
  onPaperEnter?: (candidate: ParlayCandidate) => void;
  onPaperExit?: (position: PaperPosition) => void;
  enteringSymbol?: string | null;
}

export function ParlayBoard({
  data,
  updated,
  refreshing,
  stale,
  onRetry,
  positions = [],
  positionsStale = false,
  onPaperEnter,
  onPaperExit,
  enteringSymbol,
}: ParlayBoardProps) {
  const [filter, setFilter] = useState<Filter>('ALL');
  const shown = useMemo(
    () => data.candidates.filter((candidate) => matches(candidate, filter)),
    [data.candidates, filter],
  );
  const qualified = data.candidates.filter(
    (candidate) => candidate.signal_status === 'BUY' || candidate.signal_status === 'WATCH',
  );
  const hero = qualified[0];
  // Keep aggregate reporting resilient while a cached response from an older
  // local backend is replaced after an incremental deployment.
  const scannerHealth = data.scanner_health ?? {
    candidate_count: data.candidates.length,
    unavailable_candidate_count: data.candidates.filter((candidate) => candidate.signal_status === 'UNAVAILABLE').length,
    provider_status: data.provider_status.status,
  };

  return <section id="parlay" className="parlay-board" aria-labelledby="parlay-title">
    <header className="parlay-header">
      <div className="brand-lockup">
        <img
          src="/parlay-logo.png"
          alt="Parlay logo"
          width="1395"
          height="446"
          decoding="async"
        />
        <div>
          <p className="eyebrow">Paper 0DTE Decision Board</p>
          <h1 id="parlay-title" className="sr-only">Parlay</h1>
          <p>Disciplined, paper-only market research</p>
        </div>
      </div>
      <ProviderStatus provider={data.provider_status} updated={updated} refreshing={refreshing} onRefresh={onRetry} />
    </header>

    <div className="board-meta">
      <p className="paper-notice"><strong>Paper only</strong><span>No live orders are placed.</span></p>
      <p className="freshness" aria-label="Aggregate scanner health">
        Scanner health: <strong>{scannerHealth.candidate_count} candidates</strong>
        <span>{scannerHealth.unavailable_candidate_count} unavailable</span>
        <span>Provider {scannerHealth.provider_status}</span>
      </p>
    </div>
    {stale && <StaleDataWarning updated={updated} onRetry={onRetry} />}

    {!hero && <div className="empty-state">
      <strong>NO QUALIFIED PARLAYS RIGHT NOW</strong>
      <span>Continue scanning. Do not force a trade.</span>
    </div>}
    {hero && <ParlayTicket
      candidate={hero}
      hero
      onPaperEnter={onPaperEnter}
      entering={enteringSymbol === hero.symbol}
    />}
    <div className="supporting-tickets">
      {qualified.slice(1, 3).map((candidate) => <ParlayTicket
        candidate={candidate}
        key={candidate.symbol}
        onPaperEnter={onPaperEnter}
        entering={enteringSymbol === candidate.symbol}
      />)}
    </div>

    <PaperPositions
      positions={positions}
      stale={positionsStale}
      onExit={(position) => onPaperExit?.(position)}
    />

    <section className="scanner-section" aria-labelledby="scanner-title">
      <div className="scanner-heading">
        <div><p className="eyebrow">Full universe</p><h2 id="scanner-title">12-symbol scanner board</h2></div>
        <span>{shown.length} shown</span>
      </div>
      <ScannerFilters candidates={data.candidates} active={filter} onChange={setFilter} />
      <ParlayScannerTable candidates={shown} />
    </section>
  </section>;
}
