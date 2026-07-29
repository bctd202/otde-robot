import type { ParlayCandidate } from '../types';
import { DirectionBadge } from './DirectionBadge';
import { SignalBadge } from './SignalBadge';
import { TradePlan } from './TradePlan';
const value=(number:number|null)=>number===null?'—':`$${number.toFixed(2)}`;
export function ParlayTicket({candidate,hero=false,onPaperEnter,entering=false}:{candidate:ParlayCandidate;hero?:boolean;onPaperEnter?:(candidate:ParlayCandidate)=>void;entering?:boolean}) { return <article className={`parlay-ticket ${hero?'hero-ticket':''}`}>
  {hero&&<p className="ticket-kicker">Best Play Right Now</p>}
  <div className="ticket-top"><span className="ranking">#{candidate.ranking_position}</span><div><h3>{candidate.symbol}</h3><DirectionBadge direction={candidate.direction}/></div><SignalBadge status={candidate.signal_status}/><div className="score"><strong>{candidate.score.toFixed(1)}</strong><span>{candidate.score_label}</span></div></div>
  <p className="primary-action">{candidate.primary_action}</p>
  {candidate.contract&&<div className="contract-line"><strong>{candidate.contract.option_symbol}</strong><span>Bid {value(candidate.contract.bid)}</span><span>Ask {value(candidate.contract.ask)}</span><span>Cost {value(candidate.contract_cost)}</span></div>}
  <TradePlan candidate={candidate}/>
  {candidate.reasons.length>0&&<div className="ticket-reasons"><span>WHY THIS RANKS</span><ul>{candidate.reasons.slice(0,3).map(reason=><li key={reason}>✓ {reason}</li>)}</ul></div>}
  {candidate.signal_status==='BUY'&&candidate.contract&&onPaperEnter&&<button type="button" className="paper-enter" disabled={entering} onClick={()=>onPaperEnter(candidate)}>{entering?'Recording…':'Paper Enter'}</button>}
</article>; }
