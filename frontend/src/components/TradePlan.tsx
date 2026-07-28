import type { ParlayCandidate } from '../types';
const money=(value:number|null)=>value===null?'—':`$${value.toFixed(2)}`;
export function TradePlan({candidate}:{candidate:ParlayCandidate}) { if(candidate.signal_status==='PASS'||candidate.signal_status==='UNAVAILABLE') return <p className="rejection">{candidate.unavailable_reason??candidate.rejection_reasons[0]??'No qualified setup'}</p>; const side=candidate.direction==='call'?'above':'below'; const fail=candidate.direction==='call'?'below':'above'; return <div className="trade-plan">
  <div><span>{candidate.signal_status==='WATCH'?'WAITING ENTRY':'ENTRY'}</span><strong>{money(candidate.entry_low)}–{money(candidate.entry_high)}</strong></div>
  <div><span>NO CHASE</span><strong>Above {money(candidate.no_chase_price)}</strong></div>
  <div><span>TRIGGER</span><strong>{candidate.symbol} {side} {money(candidate.underlying_trigger)}</strong></div>
  <div className="risk"><span>INVALIDATION</span><strong>{candidate.symbol} {fail} {money(candidate.underlying_invalidation)}</strong></div>
  <div><span>FIRST CASH-OUT</span><strong>Option near {money(candidate.first_option_target)}</strong></div>
  <div><span>RUNNER TARGET</span><strong>Option near {money(candidate.stretch_option_target)}</strong></div>
</div>; }
