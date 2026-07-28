import type { Analytics, Dashboard, JournalSignal, ParlayResponse } from '../types';
const API = import.meta.env.VITE_API_URL ?? '/api';
async function request<T>(path:string):Promise<T> { const response=await fetch(`${API}${path}`); if(!response.ok) throw new Error(`${path} returned ${response.status}`); return response.json() as Promise<T>; }
export const getDashboard=()=>request<Dashboard>('/dashboard');
export const getJournal=()=>request<JournalSignal[]>('/journal');
export const getAnalytics=()=>request<Analytics>('/analytics');
export const getParlays=()=>request<ParlayResponse>('/parlays');
