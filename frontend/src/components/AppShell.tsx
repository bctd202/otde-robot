import {useEffect,useState} from 'react';
import type {ReactNode} from 'react';
import type {ParlayResponse} from '../types';
import {formatEasternDateTime} from '../lib/dates';
import {CollectionChecks} from './EvidenceChecks';

export const appPages=['parlay','lottery','performance','backtest-lab'] as const;
export type AppPage=typeof appPages[number];
const navigation=[
  {id:'parlay',label:'Trade Board',caption:'Live decisions',path:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'},
  {id:'lottery',label:'Lotto Lab',caption:'Two exit experiments',path:'M9 3h6 M10 3v6l-6 10q-1 2 2 2h12q3 0 2-2L14 9V3 M8 14h8'},
  {id:'performance',label:'History',caption:'Money & saved trades',path:'M3 17l5-6 5 3 8-10 M3 3v18h18'},
  {id:'backtest-lab',label:'Research',caption:'Backtests & evidence',path:'M4 4h6q2 0 2 2q0-2 2-2h6v16h-6q-2 0-2 1q0-1-2-1H4z M12 6v15'},
] as const;

export function AppShell({activePage,onNavigate,data,stale,refreshing,onRefresh,children}:{
  activePage:AppPage;onNavigate:(page:AppPage)=>void;data:ParlayResponse|null;stale:boolean;
  refreshing:boolean;onRefresh:()=>void;children:ReactNode;
}){
  const [online,setOnline]=useState(()=>navigator.onLine);
  useEffect(()=>{
    const update=()=>setOnline(navigator.onLine);
    window.addEventListener('online',update);window.addEventListener('offline',update);
    return()=>{window.removeEventListener('online',update);window.removeEventListener('offline',update)};
  },[]);
  const health=data?.scanner_health;
  const session=health?.market_session;
  const lastScan=health?.last_completed_scan_at;
  const connection=!online?'Offline · last saved data':stale?'Server unavailable · last saved data':data?'Server connected':'Connecting to Parlay';
  const market=session==='regular'?'Market open':session?'Market closed':'Market status unknown';
  const selected=navigation.find(item=>item.id===activePage)!;
  return <div className="app-shell">
    <a className="skip-link" href="#app-content" onClick={event=>{event.preventDefault();document.getElementById('app-content')?.focus()}}>Skip to workspace</a>
    <aside className="app-rail" aria-label="Parlay app navigation">
      <div className="app-brand"><img src="/favicon.svg" alt="" width="36" height="36"/><div><strong>PARLAY</strong><small>Research workspace</small></div></div>
      <nav aria-label="Primary">{navigation.map(item=><a key={item.id} href={`#${item.id}`} aria-label={item.label} aria-current={activePage===item.id?'page':undefined} onClick={event=>{if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();onNavigate(item.id)}} title={item.label}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d={item.path}/></svg><span>{item.label}<small>{item.caption}</small></span>
      </a>)}</nav>
      <div className="app-rail-note"><span className="status-dot"/> Server-owned scanning<small>Closing this screen does not stop the server.</small></div>
    </aside>
    <div className="app-workspace">
      <header className="app-toolbar"><div className="app-location"><small>PARLAY / WORKSPACE</small><strong>{selected.label}</strong></div>
        <div className="app-status" aria-label="Workspace status">
          <span className="paper-mode">{data?.paper_only?'Paper mode':'Mode unconfirmed'}</span>
          {data&&<span className="feed-mode">{data.provider_status.provider} · {data.provider_status.mode} feed</span>}
          <span>{market}{health?.operator_hold?' · Scanner held':''}</span>
          <span className={!online||stale?'connection-warning':'connection-state'} role="status">{connection}</span>
          <small className="last-scan">Last completed scan: {lastScan?formatEasternDateTime(lastScan):'Not yet verified'}</small>
          <CollectionChecks evidence={health?.collection_evidence}/>
        </div>
        <button className="app-refresh" disabled={refreshing} onClick={onRefresh} aria-label="Refresh workspace" title="Refresh saved server data">↻<span>{refreshing?'Checking':'Refresh'}</span></button>
      </header>
      <main className="app-main" id="app-content" tabIndex={-1}>{children}</main>
    </div>
  </div>;
}
