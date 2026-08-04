import type { Analytics, Dashboard, JournalSignal, PaperPosition, PaperPositionsResponse, ParlayCandidate, ParlayResponse } from '../types';
const API = import.meta.env.VITE_API_URL ?? '/api';
async function request<T>(path:string):Promise<T> { const response=await fetch(`${API}${path}`); if(!response.ok) throw new Error(`${path} returned ${response.status}`); return response.json() as Promise<T>; }
async function send<T>(path:string,body:unknown):Promise<T> { const response=await fetch(`${API}${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!response.ok){const detail=await response.json().catch(()=>({detail:`request returned ${response.status}`})) as {detail?:string};throw new Error(detail.detail??`request returned ${response.status}`)}return response.json() as Promise<T> }
export const getDashboard=()=>request<Dashboard>('/dashboard');
export const getJournal=()=>request<JournalSignal[]>('/journal');
export const getAnalytics=()=>request<Analytics>('/analytics');
export const getParlays=()=>request<ParlayResponse>('/parlays');
export const getPaperPositions=()=>request<PaperPositionsResponse>('/paper-positions');
export const paperEnter=(candidate:ParlayCandidate,providerMode:string)=>{
  if(!candidate.contract||candidate.underlying_price===null||candidate.underlying_trigger===null||candidate.underlying_invalidation===null||candidate.first_underlying_target===null||candidate.stretch_underlying_target===null||candidate.first_option_target===null||candidate.stretch_option_target===null)throw new Error('Candidate trade plan is incomplete');
  if(!candidate.actionable||candidate.verification_status!=='verified')throw new Error('Paper entry requires a verified Tradier contract');
  return send<PaperPosition>('/paper-positions',{symbol:candidate.symbol,option_symbol:candidate.contract.option_symbol,direction:candidate.direction,expiration:candidate.contract.expiration,strike:candidate.contract.strike,quantity:1,option_ask:candidate.contract.ask,underlying_entry_price:candidate.underlying_price,underlying_trigger:candidate.underlying_trigger,underlying_invalidation:candidate.underlying_invalidation,first_underlying_target:candidate.first_underlying_target,stretch_underlying_target:candidate.stretch_underlying_target,first_option_target:candidate.first_option_target,stretch_option_target:candidate.stretch_option_target,score:candidate.score,score_label:candidate.score_label,reasons:candidate.reasons,signal_status:candidate.signal_status,provider_mode:providerMode,provider:candidate.provider,verification_status:candidate.verification_status,actionable:candidate.actionable,entry_timestamp:new Date().toISOString(),paper_only:true});
};
export const exitPaperPosition=(id:number,reason:string)=>send<PaperPosition>(`/paper-positions/${id}/exit`,{reason,paper_only:true});
