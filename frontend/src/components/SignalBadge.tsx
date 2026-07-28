import type { SignalStatus } from '../types';
export function SignalBadge({status}:{status:SignalStatus}) { return <span className={`signal signal-${status.toLowerCase()}`}>{status==='MISSED'?'MISSED — DO NOT CHASE':status}</span>; }
