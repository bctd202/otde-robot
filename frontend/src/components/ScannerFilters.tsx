import type { ParlayCandidate } from '../types';
export type Filter='ALL'|'CALLS'|'PUTS'|'BUY'|'WATCH'|'MISSED'|'PASS';
const filters:Filter[]=['ALL','CALLS','PUTS','BUY','WATCH','MISSED','PASS'];
export const matches=(candidate:ParlayCandidate,filter:Filter)=>filter==='ALL'||(filter==='CALLS'&&candidate.direction==='call')||(filter==='PUTS'&&candidate.direction==='put')||candidate.signal_status===filter;
export function ScannerFilters({candidates,active,onChange}:{candidates:ParlayCandidate[];active:Filter;onChange:(filter:Filter)=>void}) { return <div className="scanner-filters" aria-label="Scanner filters">{filters.map(filter=><button type="button" aria-pressed={active===filter} onClick={()=>onChange(filter)} key={filter}>{filter} <span>{candidates.filter(candidate=>matches(candidate,filter)).length}</span></button>)}</div>; }
