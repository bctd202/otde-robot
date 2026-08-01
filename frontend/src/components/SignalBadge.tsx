import type { SignalStatus } from '../types';
const labels:Record<SignalStatus,string>={BUY:'BUY NOW',WATCH:'WAIT',MISSED:'MISSED — DO NOT CHASE',PASS:'NO TRADE',UNAVAILABLE:'UNAVAILABLE'};
export function SignalBadge({status}:{status:SignalStatus}) { return <span className={`signal signal-${status.toLowerCase()}`}>{labels[status]}</span>; }
