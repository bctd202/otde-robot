import { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { addDailyWatch, exitPaperPosition, getDailyWatch, getPaperPositions, getParlays, getSignalAlerts, paperEnter, removeDailyWatch } from './api/client';
import { ParlayBoard, ParlaySkeleton } from './components/ParlayBoard';
import { Performance } from './components/Performance';
import { BacktestLab } from './components/BacktestLab';
import { DailyWatch } from './components/DailyWatch';
import { SignalAlerts } from './components/SignalAlerts';
import { StrategyControls } from './components/StrategyControls';
import { LotteryLab } from './components/LotteryTracker';
import type { DailyWatchResponse, PaperPosition, ParlayCandidate, ParlayResponse, SignalAlert, StrategyMode, StrategyView } from './types';
import { parseApiTimestamp } from './lib/dates';
import './style.css';
import './visual-history.css';

export const PARLAY_REFRESH_INTERVAL_MS = 15_000;

const statusOrder:Record<ParlayCandidate['signal_status'],number>={BUY:0,WATCH:1,MISSED:2,PASS:3,UNAVAILABLE:4};

export function stabilizeCandidateOrder(next:ParlayResponse,previous:ParlayResponse|null):ParlayResponse {
  if(!previous)return next;
  const priorIndex=new Map(previous.candidates.map((candidate,index)=>[`${candidate.strategy_mode}:${candidate.symbol}`,index]));
  const candidates=[...next.candidates].sort((left,right)=>{
    const statusDifference=statusOrder[left.signal_status]-statusOrder[right.signal_status];
    if(statusDifference!==0)return statusDifference;
    if(Math.abs(left.score-right.score)>1)return right.score-left.score;
    return (priorIndex.get(`${left.strategy_mode}:${left.symbol}`)??Number.MAX_SAFE_INTEGER)-(priorIndex.get(`${right.strategy_mode}:${right.symbol}`)??Number.MAX_SAFE_INTEGER);
  }).map((candidate,index)=>({...candidate,ranking_position:index+1}));
  return {...next,candidates};
}

export function App() {
  const [parlays,setParlays]=useState<ParlayResponse|null>(null);
  const [dailyWatch,setDailyWatch]=useState<DailyWatchResponse|null>(null);
  const [dailyWatchBusy,setDailyWatchBusy]=useState(false);
  const [dailyWatchMessage,setDailyWatchMessage]=useState('');
  const [parlayStale,setParlayStale]=useState(false);
  const [parlayRefreshing,setParlayRefreshing]=useState(false);
  const [positions,setPositions]=useState<PaperPosition[]>([]);
  const [positionsStale,setPositionsStale]=useState(false);
  const [enteringSymbol,setEnteringSymbol]=useState<string|null>(null);
  const [paperFeedback,setPaperFeedback]=useState('');
  const [signalAlerts,setSignalAlerts]=useState<SignalAlert[]>([]);
  const [strategyView,setStrategyView]=useState<StrategyView>('ALL');
  const [strategyAlerts,setStrategyAlerts]=useState<Record<StrategyMode,boolean>>(()=>{
    try{const saved=localStorage.getItem('parlay-strategy-alerts');return saved?JSON.parse(saved) as Record<StrategyMode,boolean>:{ONE_MIN_0DTE:true,STRUCTURED_INTRADAY:true}}catch{return {ONE_MIN_0DTE:true,STRUCTURED_INTRADAY:true}}
  });
  const [lastParlayUpdate,setLastParlayUpdate]=useState<Date|null>(null);
  const parlayRequest=useRef(false);
  const latestAlertId=useRef(0);
  const alertsInitialized=useRef(false);
  useEffect(()=>{void getDailyWatch().then(setDailyWatch).catch(()=>setDailyWatchMessage('Watch Today is temporarily unavailable.'))},[]);
  const refreshParlays=useCallback(async()=>{if(parlayRequest.current)return;parlayRequest.current=true;setParlayRefreshing(true);try{
    const [boardResult,positionsResult,alertsResult]=await Promise.allSettled([getParlays(),getPaperPositions(),getSignalAlerts()]);
    if(boardResult.status==='fulfilled'){setParlays(previous=>stabilizeCandidateOrder(boardResult.value,previous));setLastParlayUpdate(parseApiTimestamp(boardResult.value.scanner_health?.last_completed_scan_at)??new Date());setParlayStale(false)}else setParlayStale(true);
    if(positionsResult.status==='fulfilled'){setPositions(positionsResult.value.positions);setPositionsStale(false)}else setPositionsStale(true);
    if(alertsResult.status==='fulfilled'&&Array.isArray(alertsResult.value.alerts)){
      const incoming=alertsResult.value.alerts.filter(alert=>alert.id>latestAlertId.current);
      setSignalAlerts(alertsResult.value.alerts);
      if(alertsInitialized.current&&typeof Notification!=='undefined'&&Notification.permission==='granted')incoming.filter(alert=>{const mode=alert.payload.strategy_mode as StrategyMode|undefined;return !mode||strategyAlerts[mode]}).forEach(alert=>new Notification(`${alert.symbol} · ${alert.event_type.replaceAll('_',' ')}`,{body:alert.message,tag:`parlay-${alert.id}`}));
      latestAlertId.current=Math.max(latestAlertId.current,Number(alertsResult.value.latest_id)||0);
      alertsInitialized.current=true;
    }
  }finally{parlayRequest.current=false;setParlayRefreshing(false)}},[strategyAlerts]);
  useEffect(()=>{void refreshParlays();const timer=window.setInterval(()=>void refreshParlays(),PARLAY_REFRESH_INTERVAL_MS);return()=>window.clearInterval(timer)},[refreshParlays]);
  const enterPaper=useCallback(async(candidate:ParlayCandidate)=>{if(!parlays)return;setEnteringSymbol(`${candidate.strategy_mode}:${candidate.symbol}`);setPaperFeedback('');try{await paperEnter(candidate,parlays.provider_status.mode);setPaperFeedback(`${candidate.symbol} ${candidate.strategy_mode==='STRUCTURED_INTRADAY'?'structured':'1-minute'} paper position recorded at the current ask.`);await refreshParlays()}catch(reason){setPaperFeedback(reason instanceof Error?reason.message:'Unable to record paper position')}finally{setEnteringSymbol(null)}},[parlays,refreshParlays]);
  const changeStrategyAlert=useCallback((mode:StrategyMode,enabled:boolean)=>{setStrategyAlerts(previous=>{const next={...previous,[mode]:enabled};localStorage.setItem('parlay-strategy-alerts',JSON.stringify(next));return next})},[]);
  const exitPaper=useCallback(async(position:PaperPosition)=>{if(!window.confirm(`Close the simulated ${position.symbol} position? This does not place an order.`))return;setPaperFeedback('');try{await exitPaperPosition(position.id,'USER CONFIRMED PAPER EXIT');setPaperFeedback(`${position.symbol} paper position closed.`);await refreshParlays()}catch(reason){setPaperFeedback(reason instanceof Error?reason.message:'Unable to close paper position')}},[refreshParlays]);
  const addWatch=useCallback(async(symbol:string)=>{setDailyWatchBusy(true);setDailyWatchMessage('');try{const result=await addDailyWatch(symbol);setDailyWatch(result);setDailyWatchMessage(`${symbol} added for today.`);await refreshParlays()}catch(reason){setDailyWatchMessage(reason instanceof Error?reason.message:'Unable to add ticker')}finally{setDailyWatchBusy(false)}},[refreshParlays]);
  const removeWatch=useCallback(async(symbol:string)=>{setDailyWatchBusy(true);setDailyWatchMessage('');try{const result=await removeDailyWatch(symbol);setDailyWatch(result);setDailyWatchMessage(`${symbol} removed.`);await refreshParlays()}catch(reason){setDailyWatchMessage(reason instanceof Error?reason.message:'Unable to remove ticker')}finally{setDailyWatchBusy(false)}},[refreshParlays]);
  return <main>
    <nav className="top-navigation" aria-label="Primary"><a href="#parlay">Trade Board</a><a href="#lottery">Lottery Plays</a><a href="#performance">Play History</a><a href="#backtest-lab">Backtests</a></nav>
    {paperFeedback&&<p className="paper-feedback" role="status">{paperFeedback}</p>}
    <StrategyControls view={strategyView} onViewChange={setStrategyView} alerts={strategyAlerts} onAlertChange={changeStrategyAlert}/>
    <DailyWatch data={dailyWatch} busy={dailyWatchBusy} message={dailyWatchMessage} onAdd={symbol=>void addWatch(symbol)} onRemove={symbol=>void removeWatch(symbol)}/>
    <SignalAlerts alerts={signalAlerts}/>
    {parlays?<ParlayBoard data={parlays} selectedStrategy={strategyView} updated={lastParlayUpdate} refreshing={parlayRefreshing} stale={parlayStale} onRetry={()=>void refreshParlays()} positions={positions} positionsStale={positionsStale} onPaperEnter={candidate=>void enterPaper(candidate)} onPaperExit={position=>void exitPaper(position)} enteringSymbol={enteringSymbol}/>:<ParlaySkeleton/>}
    <LotteryLab/>
    <Performance/>
    <BacktestLab/>
    <footer>Parlay paper-only research · No brokerage adapter or order-routing path exists.</footer>
  </main>;
}

const root=document.getElementById('root');
if(root) createRoot(root).render(<App/>);
