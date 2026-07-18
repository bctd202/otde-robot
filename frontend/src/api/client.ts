import type { Analytics, Dashboard, JournalSignal } from '../types';
const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api';
async function request<T>(path:string):Promise<T> { const response=await fetch(`${API}${path}`); if(!response.ok) throw new Error(`${path} returned ${response.status}`); return response.json() as Promise<T>; }
export const getDashboard=()=>request<Dashboard>('/dashboard');
export const getJournal=()=>request<JournalSignal[]>('/journal');
export const getAnalytics=()=>request<Analytics>('/analytics');
