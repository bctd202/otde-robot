import type { PaperPosition } from '../types';
import { formatDateOnly, formatEasternDateTime } from '../lib/dates';

const dollars=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'});
const price=(value:number|null)=>value===null?'—':dollars.format(value);

export function PaperPositions({positions,stale,onExit}:{positions:PaperPosition[];stale:boolean;onExit:(position:PaperPosition)=>void}){
  const active=positions.filter(position=>position.lifecycle_status==='ACTIVE');
  const expired=positions.filter(position=>position.lifecycle_status==='EXPIRED');
  const closed=positions.filter(position=>position.lifecycle_status==='CLOSED');
  return <div className="paper-positions-region">
    <section className="paper-positions" aria-labelledby="open-paper-title">
      <div className="paper-section-heading"><div><p className="eyebrow">PAPER MANAGEMENT</p><h2 id="open-paper-title">Open Paper Positions</h2></div><span>{active.length} active</span></div>
      {stale&&<p className="position-stale" role="alert">Position data is stale. Retaining the last known position state.</p>}
      {active.length===0?<p className="paper-empty">No open paper positions.</p>:<div className="position-grid">{active.map(position=><article className={`position-card decision-${position.decision_status.toLowerCase()}`} key={position.id}>
        <header><div><h3>{position.symbol} <span>{position.direction.toUpperCase()}</span></h3><strong>{position.option_symbol}</strong></div><span className="decision-badge">{position.decision_status.replace('_',' ')}</span></header>
        <p className="position-action">{position.next_action}</p>
        <dl><div><dt>Entry option</dt><dd>{price(position.entry_option_price)}</dd></div><div><dt>Current option</dt><dd>{price(position.current_option_price)}</dd></div><div><dt>Simulated debit</dt><dd>{dollars.format(position.total_debit)}</dd></div><div><dt>Unrealized P&amp;L</dt><dd>{position.unrealized_pnl===null?'—':`${dollars.format(position.unrealized_pnl)} (${position.pnl_percent?.toFixed(2)}%)`}</dd></div><div><dt>Expiration</dt><dd>{formatDateOnly(position.expiration)}</dd></div><div><dt>Underlying entry / current</dt><dd>{price(position.entry_underlying_price)} / {price(position.current_underlying_price)}</dd></div><div><dt>Trigger</dt><dd>{price(position.underlying_trigger)}</dd></div><div><dt>Invalidation</dt><dd>{price(position.underlying_invalidation)}</dd></div><div><dt>First target</dt><dd>{price(position.first_underlying_target)}</dd></div><div><dt>Runner target</dt><dd>{price(position.stretch_underlying_target)}</dd></div><div><dt>Opened</dt><dd>{formatEasternDateTime(position.opened_at)}</dd></div></dl>
        <button className="paper-exit" type="button" onClick={()=>onExit(position)}>Exit Paper Position</button>
      </article>)}</div>}
    </section>
    {expired.length>0&&<section className="recent-exits expired-positions" aria-labelledby="expired-positions-title"><h2 id="expired-positions-title">Expired Paper Positions</h2>{expired.map(position=><article key={position.id}><strong>{position.symbol} {position.direction.toUpperCase()}</strong><span>Expired {formatDateOnly(position.expiration)}</span><span>Last-known option {price(position.current_option_price)}</span><span>Last-known underlying {price(position.current_underlying_price)}</span><span>Historical / stale — no settlement price recorded</span><time>Last marked {formatEasternDateTime(position.last_marked_at)}</time></article>)}</section>}
    {closed.length>0&&<section className="recent-exits" aria-labelledby="recent-exits-title"><h2 id="recent-exits-title">Recent Paper Exits</h2>{closed.map(position=><article key={position.id}><strong>{position.symbol} {position.direction.toUpperCase()}</strong><span>Entry {price(position.entry_option_price)}</span><span>Exit {price(position.exit_option_price)}</span><span>Realized {position.realized_pnl===null?'—':dollars.format(position.realized_pnl)}</span><span>{position.exit_reason}</span><time>{formatEasternDateTime(position.opened_at)} → {formatEasternDateTime(position.closed_at)}</time></article>)}</section>}
  </div>;
}
