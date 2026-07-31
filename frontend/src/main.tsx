import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { exitPaperPosition, getAnalytics, getDashboard, getJournal, getPaperPositions, getParlays, paperEnter } from './api/client';
import { CandlestickChart } from './components/CandlestickChart';
import { ParlayBoard, ParlaySkeleton } from './components/ParlayBoard';
import type { Analytics, Dashboard, JournalSignal, LiquidityLevels, PaperPosition, ParlayCandidate, ParlayResponse } from './types';
import './style.css';

export const PARLAY_REFRESH_INTERVAL_MS = 120_000;

const statusOrder:Record<ParlayCandidate['signal_status'],number>={BUY:0,WATCH:1,MISSED:2,PASS:3,UNAVAILABLE:4};

export function stabilizeCandidateOrder(next:ParlayResponse,previous:ParlayResponse|null):ParlayResponse {
  if(!previous)return next;
  const priorIndex=new Map(previous.candidates.map((candidate,index)=>[candidate.symbol,index]));
  const candidates=[...next.candidates].sort((left,right)=>{
    const statusDifference=statusOrder[left.signal_status]-statusOrder[right.signal_status];
    if(statusDifference!==0)return statusDifference;
    if(Math.abs(left.score-right.score)>1)return right.score-left.score;
    return (priorIndex.get(left.symbol)??Number.MAX_SAFE_INTEGER)-(priorIndex.get(right.symbol)??Number.MAX_SAFE_INTEGER);
  }).map((candidate,index)=>({...candidate,ranking_position:index+1}));
  return {...next,candidates};
}

function Card({title,children,danger=false,id}:{title:string;children:React.ReactNode;danger?:boolean;id?:string}) { return <section id={id} className={`card ${danger?'danger':''}`}><h2>{title}</h2>{children}</section> }
function Metric({label,value}:{label:string;value:React.ReactNode}) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div> }
function formatLevels(values:number[]):string { return values.length ? values.map(value=>value.toFixed(2)).join(', ') : 'None detected'; }
function LiquidityMap({levels}:{levels:Record<string,LiquidityLevels>}) {
  const entries=Object.entries(levels);
  if(entries.length===0)return <div className="empty-state"><strong>Liquidity levels unavailable</strong><p>The data provider did not return intraday levels for any symbol.</p></div>;
  return <>{entries.map(([symbol,item])=><details key={symbol}><summary>{symbol}</summary><div className="levels"><Metric label="Previous day high / low" value={`${item.previous_day_high.toFixed(2)} / ${item.previous_day_low.toFixed(2)}`}/><Metric label="Opening range high / low" value={`${item.opening_range_high.toFixed(2)} / ${item.opening_range_low.toFixed(2)}`}/><Metric label="Session high / low" value={`${item.session_high.toFixed(2)} / ${item.session_low.toFixed(2)}`}/><Metric label="VWAP" value={item.vwap.toFixed(2)}/><Metric label="Equal highs" value={formatLevels(item.equal_highs)}/><Metric label="Equal lows" value={formatLevels(item.equal_lows)}/></div></details>)}</>;
}

export function App() {
  const [dashboard,setDashboard]=useState<Dashboard|null>(null);
  const [journal,setJournal]=useState<JournalSignal[]>([]);
  const [analytics,setAnalytics]=useState<Analytics|null>(null);
  const [parlays,setParlays]=useState<ParlayResponse|null>(null);
  const [parlayStale,setParlayStale]=useState(false);
  const [parlayRefreshing,setParlayRefreshing]=useState(false);
  const [positions,setPositions]=useState<PaperPosition[]>([]);
  const [positionsStale,setPositionsStale]=useState(false);
  const [enteringSymbol,setEnteringSymbol]=useState<string|null>(null);
  const [paperFeedback,setPaperFeedback]=useState('');
  const [lastParlayUpdate,setLastParlayUpdate]=useState<Date|null>(null);
  const parlayRequest=useRef(false);
  const [error,setError]=useState('');
  useEffect(()=>{ Promise.all([getDashboard(),getJournal(),getAnalytics()]).then(([d,j,a])=>{setDashboard(d);setJournal(j);setAnalytics(a)}).catch((reason:Error)=>setError(reason.message)); },[]);
  const refreshParlays=useCallback(async()=>{if(parlayRequest.current)return;parlayRequest.current=true;setParlayRefreshing(true);try{const [boardResult,positionsResult]=await Promise.all([getParlays(),getPaperPositions()]);setParlays(previous=>stabilizeCandidateOrder(boardResult,previous));setPositions(positionsResult.positions);setLastParlayUpdate(new Date());setParlayStale(false);setPositionsStale(false)}catch{setParlayStale(true);setPositionsStale(true)}finally{parlayRequest.current=false;setParlayRefreshing(false)}},[]);
  useEffect(()=>{void refreshParlays();const timer=window.setInterval(()=>void refreshParlays(),PARLAY_REFRESH_INTERVAL_MS);return()=>window.clearInterval(timer)},[refreshParlays]);
  const enterPaper=useCallback(async(candidate:ParlayCandidate)=>{if(!parlays)return;setEnteringSymbol(candidate.symbol);setPaperFeedback('');try{await paperEnter(candidate,parlays.provider_status.mode);setPaperFeedback(`${candidate.symbol} paper position recorded at the current ask.`);await refreshParlays()}catch(reason){setPaperFeedback(reason instanceof Error?reason.message:'Unable to record paper position')}finally{setEnteringSymbol(null)}},[parlays,refreshParlays]);
  const exitPaper=useCallback(async(position:PaperPosition)=>{if(!window.confirm(`Close the simulated ${position.symbol} position? This does not place an order.`))return;setPaperFeedback('');try{await exitPaperPosition(position.id,'USER CONFIRMED PAPER EXIT');setPaperFeedback(`${position.symbol} paper position closed.`);await refreshParlays()}catch(reason){setPaperFeedback(reason instanceof Error?reason.message:'Unable to close paper position')}},[refreshParlays]);
  const chartQuote=dashboard?.quotes.find(quote=>quote.symbol==='SPY'&&Boolean(dashboard.levels[quote.symbol]))
    ?? dashboard?.quotes.find(quote=>Boolean(dashboard.levels[quote.symbol]));
  const chartLevels=chartQuote?dashboard?.levels[chartQuote.symbol]:undefined;
  const chartBias=chartQuote?dashboard?.directional_bias[chartQuote.symbol]:undefined;
  const isMock=dashboard?.provider_status.mode==='mock'||dashboard?.provider_status.provider==='mock';
  const isDelayed=Boolean(dashboard&&dashboard.provider_status.delay_seconds>0);
  return <main>
    {paperFeedback&&<p className="paper-feedback" role="status">{paperFeedback}</p>}
    {parlays?<ParlayBoard data={parlays} updated={lastParlayUpdate} refreshing={parlayRefreshing} stale={parlayStale} onRetry={()=>void refreshParlays()} positions={positions} positionsStale={positionsStale} onPaperEnter={candidate=>void enterPaper(candidate)} onPaperExit={position=>void exitPaper(position)} enteringSymbol={enteringSymbol}/>:<ParlaySkeleton/>}
    <nav>{['parlay','context','charts','structured','lottery','journal','analytics'].map(item=><a key={item} href={`#${item}`}>{item}</a>)}</nav>
    {error&&<Card title="Unable to load market context" danger><p>{error}</p><p>The Parlay board will continue retrying independently.</p></Card>}
    {!dashboard&&<section className="legacy-skeleton" aria-label="Loading market context"/>}
    {dashboard&&<>
    <div id="context" className="section-heading"><p className="eyebrow">SECONDARY</p><h2>Market Context</h2></div>
    <div className={`mock-banner ${isMock?'mock':isDelayed?'delayed':'live'}`}><strong>{isMock?'MOCK DATA — NOT LIVE':isDelayed?'DELAYED MARKET DATA':'LIVE MARKET DATA'}</strong><span>{dashboard.provider_status.message}</span></div>
    <section id="command" className="quote-row">{dashboard.quotes.map(q=><div className="quote" key={q.symbol}><span>{q.symbol}</span><strong>${q.price.toFixed(2)}</strong><small>{dashboard.directional_bias[q.symbol] ?? 'Bias unavailable'}</small></div>)}<div className="quote"><span>VOL PROXY</span><strong>{dashboard.volatility_proxy ?? 'N/A'}</strong><small>{dashboard.market_session} session</small></div></section>
    <div className="grid"><Card title="Feed & Account"><Metric label="Provider" value={dashboard.provider_status.provider.toUpperCase()}/><Metric label="Feed status" value={dashboard.provider_status.status}/><Metric label="Delay" value={`${dashboard.provider_status.delay_seconds}s`}/><Metric label="Paper equity" value={`$${Number(dashboard.paper_account.equity).toLocaleString()}`}/><Metric label="Kill switch" value={dashboard.paper_account.kill_switch?'ON':'ready'}/></Card><Card title="Liquidity Map"><LiquidityMap levels={dashboard.levels}/></Card><Card title="Decision State">{dashboard.no_trade?<div className="no-trade">NO TRADE<span>Capital protected. No rules qualified.</span></div>:<div className="qualified">QUALIFIED SETUPS<span>Rules passed; execution remains paper-only.</span></div>}<p>{dashboard.news_warning}</p></Card></div>
    <Card id="structured" title={`Structured Setups · ${dashboard.normal_setups.length}`}>{dashboard.normal_setups.length===0?<p>No qualifying structured setups.</p>:dashboard.normal_setups.map(s=><article className="setup" key={`${s.symbol}-${s.name}`}><div><span className="tag">{s.symbol} · {s.direction}</span><h3>{s.name}</h3><p>{s.confluences.join(' · ')}</p></div><div className="trade-grid"><Metric label="Grade" value={s.grade}/><Metric label="Trigger" value={s.entry_trigger}/><Metric label="Invalidation" value={s.invalidation}/><Metric label="Target 1 / 2" value={`${s.target1} / ${s.target2}`}/><Metric label="Reward : risk" value={`${s.reward_risk}:1`}/><Metric label="Matching contract" value={s.contract?.option_symbol ?? 'none'}/></div></article>)}</Card>
    <Card id="lottery" title={`Lottery Lab · ${dashboard.lottery_setups.length}`} danger><div className="risk-warning"><strong>Highly speculative. Most lottery contracts are expected to expire worthless.</strong><span>Maximum modeled loss is the full debit shown. Estimates are not guarantees.</span></div>{dashboard.lottery_setups.length===0?<p>No lottery candidates.</p>:dashboard.lottery_setups.map(l=><article className="lotto" key={`${l.symbol}-${l.strike}-${l.right}`}><div><span className="tag orange">{l.symbol} {l.right.toUpperCase()} {l.strike}</span><h3>Momentum runner · score {l.setup_score}</h3><p>{l.explanation}</p></div><div className="trade-grid"><Metric label="Bid / ask" value={`${l.bid} / ${l.ask}`}/><Metric label="Maximum loss" value={`$${l.total_debit}`}/><Metric label="Spread" value={`${l.spread_percent}%`}/><Metric label="Delta / gamma" value={`${l.delta} / ${l.gamma}`}/><Metric label="Trigger / invalid" value={`${l.underlying_trigger} / ${l.underlying_invalidation}`}/><Metric label="2x / 5x / 10x est." value={`${l.estimated_2x_underlying} / ${l.estimated_5x_underlying} / ${l.estimated_10x_underlying}`}/></div><ul>{l.worthless_reasons.map(reason=><li key={reason}>{reason}</li>)}</ul></article>)}</Card>
    <div className="grid"><Card id="charts" title="Chart Workspace">{chartQuote&&chartLevels?<CandlestickChart symbol={chartQuote.symbol} currentPrice={chartQuote.price} levels={chartLevels} directionalBias={chartBias ?? 'unavailable'}/>:<div className="chart-empty-state"><strong>Chart unavailable</strong><p>The live provider did not return enough intraday data to build liquidity levels.</p></div>}</Card><Card id="journal" title={`Signal Journal · ${journal.length}`}>{journal.length===0?<p>Run the seed command to create sample signals.</p>:journal.slice(0,6).map(row=><div className="journal-row" key={row.id}><span>{row.symbol}</span><strong>{row.signal_type.replace('_',' ')}</strong><small>{row.status}</small></div>)}</Card><Card id="analytics" title="Seeded Paper Analytics">{analytics&&<><div className="analytics-grid"><Metric label="Samples" value={analytics.sample_size}/><Metric label="Win rate" value={`${analytics.win_rate}%`}/><Metric label="Profit factor" value={analytics.profit_factor ?? 'N/A'}/><Metric label="Expectancy" value={`${analytics.expectancy}%`}/></div><p>{analytics.message}</p><small>Minimum sample size: {analytics.minimum_sample_size}; promising: {analytics.statistically_promising?'yes':'no'}.</small></>}</Card></div>
    <footer>Parlay paper-only research · No brokerage adapter or order-routing path exists.</footer>
    </>}
  </main>;
}

const root=document.getElementById('root');
if(root) createRoot(root).render(<App/>);
