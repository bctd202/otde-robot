import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { getLotteryTracker, getLotteryTrackers } from '../api/client';
import { formatEasternTime, parseApiTimestamp } from '../lib/dates';
import type { Lottery, LotteryTrackerDetail, LotteryTrackerPoint, LotteryTrackerSummary } from '../types';

export const LOTTERY_TRACKER_REFRESH_INTERVAL_MS=60_000;

function Metric({label,value}:{label:string;value:ReactNode}) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function money(value:number|null|undefined):string {
  return value==null?'—':`$${value.toFixed(2)}`;
}

function multiple(value:number|null|undefined):string {
  return value==null?'—':`${value.toFixed(2)}×`;
}

function pointTime(point:LotteryTrackerPoint):number {
  return parseApiTimestamp(point.observed_at)?.getTime()??0;
}

function LotteryLineChart({detail}:{detail:LotteryTrackerDetail}) {
  const points=detail.points;
  if(points.length===0)return <div className="lottery-chart-empty">Waiting for the first saved quote.</div>;
  const width=680,height=260,left=56,right=18,top=20,bottom=42;
  const plotWidth=width-left-right,plotHeight=height-top-bottom;
  const times=points.map(pointTime);
  const minTime=Math.min(...times),maxTime=Math.max(...times);
  const maxValue=Math.max(detail.tracker.entry_cost,...points.map(point=>point.bid_value),1)*1.12;
  const x=(point:LotteryTrackerPoint)=>maxTime===minTime
    ?left+plotWidth/2
    :left+((pointTime(point)-minTime)/(maxTime-minTime))*plotWidth;
  const y=(value:number)=>top+plotHeight-(value/maxValue)*plotHeight;
  const line=points.map(point=>`${x(point).toFixed(1)},${y(point.bid_value).toFixed(1)}`).join(' ');
  const entryY=y(detail.tracker.entry_cost);
  return <figure className="lottery-line-chart">
    <figcaption><strong>Sellable value by scan</strong><span>Each point uses the contract bid. Entry cost uses the first qualifying ask.</span></figcaption>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${detail.tracker.symbol} ${detail.tracker.right} ${detail.tracker.strike} sellable option value by scan`}>
      {[0,.25,.5,.75,1].map(level=>{const value=maxValue*level;const lineY=y(value);return <g key={level}><line className="lottery-grid-line" x1={left} x2={width-right} y1={lineY} y2={lineY}/><text className="lottery-axis-label" x={left-8} y={lineY+4} textAnchor="end">${value.toFixed(0)}</text></g>})}
      <line className="lottery-entry-line" x1={left} x2={width-right} y1={entryY} y2={entryY}/>
      <text className="lottery-entry-label" x={width-right} y={Math.max(top+10,entryY-5)} textAnchor="end">entry {money(detail.tracker.entry_cost)}</text>
      {points.length>1&&<polyline className="lottery-value-line" points={line}/>}
      {points.map((point,index)=><circle className={point.is_qualified?'lottery-point qualified':'lottery-point'} key={`${point.observed_at}-${index}`} cx={x(point)} cy={y(point.bid_value)} r={point.is_qualified?4.5:3.5}><title>{`${formatEasternTime(point.observed_at)} · bid ${money(point.bid_value)} · ask ${money(point.ask_value)}`}</title></circle>)}
      <text className="lottery-axis-label" x={left} y={height-14}>{formatEasternTime(points[0].observed_at)}</text>
      <text className="lottery-axis-label" x={width-right} y={height-14} textAnchor="end">{formatEasternTime(points[points.length-1].observed_at)}</text>
    </svg>
  </figure>;
}

function TrackerDetail({detail,onClose}:{detail:LotteryTrackerDetail;onClose:()=>void}) {
  const row=detail.tracker;
  return <section className="lottery-detail" id={`lottery-detail-${row.id}`}>
    <header><div><span className="tag orange">{row.symbol} {row.right.toUpperCase()} {row.strike}</span><h3>{row.option_symbol}</h3></div><button type="button" onClick={onClose}>Close chart</button></header>
    <div className="lottery-summary-grid"><Metric label="Original cost" value={money(row.entry_cost)}/><Metric label="Latest sellable" value={money(row.latest_sellable_value)}/><Metric label="Peak sellable" value={money(row.peak_sellable_value)}/><Metric label="Peak multiple" value={multiple(row.peak_multiple)}/><Metric label="2x reached" value={formatEasternTime(row.hit_2x_at)}/><Metric label="5x / 10x" value={`${formatEasternTime(row.hit_5x_at)} / ${formatEasternTime(row.hit_10x_at)}`}/></div>
    <LotteryLineChart detail={detail}/>
    <p className="lottery-method">Paper research only. This does not assume a fill at the midpoint or last trade.</p>
  </section>;
}

export function LotteryLab({setups}:{setups:Lottery[]}) {
  const [trackers,setTrackers]=useState<LotteryTrackerSummary[]>([]);
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [detail,setDetail]=useState<LotteryTrackerDetail|null>(null);
  const [loadingId,setLoadingId]=useState<string|null>(null);
  const [message,setMessage]=useState('');
  const refresh=useCallback(async()=>{
    try{
      const result=await getLotteryTrackers();
      setTrackers(Array.isArray(result.trackers)?result.trackers:[]);
    }catch{setMessage('Lottery history is temporarily unavailable.');}
  },[]);
  useEffect(()=>{void refresh();const timer=window.setInterval(()=>void refresh(),LOTTERY_TRACKER_REFRESH_INTERVAL_MS);return()=>window.clearInterval(timer)},[refresh]);
  useEffect(()=>{
    if(!selectedId)return;
    const refreshDetail=()=>void getLotteryTracker(selectedId).then(setDetail).catch(()=>setMessage('Unable to load this option history.'));
    const timer=window.setInterval(refreshDetail,LOTTERY_TRACKER_REFRESH_INTERVAL_MS);
    return()=>window.clearInterval(timer);
  },[selectedId]);
  const trackerByContract=useMemo(()=>new Map(trackers.map(row=>[row.option_symbol.toUpperCase(),row])),[trackers]);
  const currentContracts=useMemo(()=>new Set(setups.map(row=>(row.option_symbol??'').toUpperCase())),[setups]);
  const history=trackers.filter(row=>!currentContracts.has(row.option_symbol.toUpperCase()));
  const open=async(row:LotteryTrackerSummary)=>{
    if(selectedId===row.id){setSelectedId(null);setDetail(null);return;}
    setLoadingId(row.id);setMessage('');
    try{const result=await getLotteryTracker(row.id);setDetail(result);setSelectedId(row.id)}
    catch{setMessage('Unable to load this option history.')}
    finally{setLoadingId(null)}
  };
  const button=(row:LotteryTrackerSummary|undefined)=>row
    ?<button className="lottery-chart-button" type="button" aria-expanded={selectedId===row.id} aria-controls={`lottery-detail-${row.id}`} disabled={loadingId===row.id} onClick={()=>void open(row)}>{loadingId===row.id?'Loading…':selectedId===row.id?'Hide performance':'View performance'}</button>
    :<button className="lottery-chart-button" type="button" disabled>Tracking starts next scan</button>;
  return <>
    <div className="risk-warning"><strong>Highly speculative. Most lottery contracts are expected to expire worthless.</strong><span>Maximum modeled loss is the full debit shown. Estimates are not guarantees.</span></div>
    {setups.length===0?<p>No lottery candidates right now.</p>:setups.map(row=>{const tracker=trackerByContract.get((row.option_symbol??'').toUpperCase());return <article className="lotto" key={`${row.symbol}-${row.strike}-${row.right}`}><div><span className="tag orange">{row.symbol} {row.right.toUpperCase()} {row.strike}</span><h3>Momentum runner · score {row.setup_score}</h3><p>{row.explanation}</p>{button(tracker)}</div><div className="trade-grid"><Metric label="OCC symbol" value={row.option_symbol}/><Metric label="Normalized" value={row.normalized_symbol??'—'}/><Metric label="Provider / mode" value={`${row.provider} / ${row.data_mode}`}/><Metric label="Verification" value={`${row.verification_status}: ${row.verification_reason}`}/><Metric label="Bid / ask" value={`${row.bid} / ${row.ask}`}/><Metric label="Quote timestamps" value={`bid ${formatEasternTime(row.bid_timestamp)} / ask ${formatEasternTime(row.ask_timestamp)} / shown ${formatEasternTime(row.quote_timestamp)}`}/><Metric label="Expiration / type" value={`${row.expiration} ${row.right.toUpperCase()} ${row.strike}`}/><Metric label="Maximum loss" value={`$${row.total_debit}`}/><Metric label="Spread" value={`${row.spread_percent}%`}/><Metric label="Delta / gamma" value={`${row.delta} / ${row.gamma}`}/><Metric label="Trigger / invalid" value={`${row.underlying_trigger} / ${row.underlying_invalidation}`}/><Metric label="2x / 5x / 10x est." value={`${row.estimated_2x_underlying} / ${row.estimated_5x_underlying} / ${row.estimated_10x_underlying}`}/></div><ul>{row.worthless_reasons.map(reason=><li key={reason}>{reason}</li>)}</ul></article>})}
    {history.length>0&&<section className="lottery-history"><header><div><p className="eyebrow">TRACKED TODAY</p><h3>Earlier lottery plays</h3></div><span>{history.length} contract{history.length===1?'':'s'}</span></header>{history.map(row=><div className="lottery-history-row" key={row.id}><div><strong>{row.symbol} {row.right.toUpperCase()} {row.strike}</strong><small>First seen {formatEasternTime(row.first_seen_at)} · {row.point_count} scans</small></div><span>Cost {money(row.entry_cost)}</span><span>Peak {multiple(row.peak_multiple)}</span>{button(row)}</div>)}</section>}
    {message&&<p className="lottery-tracker-message" role="status">{message}</p>}
    {detail&&selectedId===detail.tracker.id&&<TrackerDetail detail={detail} onClose={()=>{setSelectedId(null);setDetail(null)}}/>}
  </>;
}
