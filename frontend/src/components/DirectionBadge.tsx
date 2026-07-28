import type { ParlayDirection } from '../types';
export function DirectionBadge({direction}:{direction:ParlayDirection}) { if(direction==='none') return null; return <span className={`direction direction-${direction}`} aria-label={`${direction} direction`}>{direction==='call'?'↑ CALL':'↓ PUT'}</span>; }
