import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { getLotteryTracker, getLotteryTrackers } from '../api/client';
import { formatDateOnly, formatEasternTime, parseApiTimestamp } from '../lib/dates';
import type { LotteryExitScenario, LotteryRuleComparison, LotterySessionSummary, LotteryTrackerDetail, LotteryTrackerList, LotteryTrackerPoint, LotteryTrackerSummary } from '../types';

export const LOTTERY_TRACKER_REFRESH_INTERVAL_MS=60_000;
const PAGE_SIZE=6;

function Metric({label,value}:{label:string;value:ReactNode}) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function money(value:number|null|undefined):string {
  return value==null?'—':`$${value.toFixed(2)}`;
}

function multiple(value:number|null|undefined):string {
  return value==null?'—':`${value.toFixed(2)}×`;
}

function percent(value:number|null|undefined):string {
  if(value==null)return '—';
  return `${value>=0?'+':''}${value.toFixed(1)}%`;
}

function timestamp(value:string):number {
  return parseApiTimestamp(value)?.getTime()??0;
}

function pointTime(point:LotteryTrackerPoint):number {
  return timestamp(point.observed_at);
}

function RuleComparisonChart({rules,cost}:{rules:LotteryRuleComparison[];cost:number}) {
  if(rules.length===0)return <div className="graph-empty"><span>No rule comparison yet</span></div>;
  const maxValue=Math.max(cost,...rules.map(rule=>rule.ending_value),1)*1.08;
  const costPosition=Math.min(100,cost/maxValue*100);
  return <div className="lottery-rule-bars" role="img" aria-label="Ending value for each lottery exit rule"><div className="lottery-rule-key"><i/>Original paper debit: {money(cost)}</div>{rules.map(rule=><div className={`lottery-rule-row ${rule.key==='observed_peak'?'hindsight':rule.pnl>=0?'positive':'negative'}`} key={rule.key}><header><span>{rule.label}</span><strong>{money(rule.ending_value)} · {percent(rule.return_percent)}</strong></header><div className="lottery-rule-track"><span style={{width:`${Math.max(1,rule.ending_value/maxValue*100)}%`}}/><i style={{left:`${costPosition}%`}} title={`Original debit ${money(cost)}`}/></div></div>)}</div>;
}

function PeakMultipleChart({trackers}:{trackers:LotteryTrackerSummary[]}) {
  if(trackers.length===0)return <div className="graph-empty"><span>No contracts in this session</span></div>;
  const ordered=[...trackers].sort((a,b)=>timestamp(a.first_seen_at)-timestamp(b.first_seen_at));
  const width=760,height=270,left=48,right=22,top=18,bottom=42;
  const plotWidth=width-left-right,plotHeight=height-top-bottom;
  const maxValue=Math.max(2,...ordered.map(row=>row.peak_multiple))*1.08;
  const x=(index:number)=>ordered.length===1?left+plotWidth/2:left+(index/(ordered.length-1))*plotWidth;
  const y=(value:number)=>top+plotHeight-(value/maxValue)*plotHeight;
  const line=ordered.map((row,index)=>`${x(index).toFixed(1)},${y(row.peak_multiple).toFixed(1)}`).join(' ');
  return <svg className="lottery-peak-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Observed peak multiple for each lottery contract">
    {[0,2,5,10].filter(level=>level<=maxValue).map(level=><g key={level}><line className={level===0?'graph-zero':'lottery-threshold-line'} x1={left} x2={width-right} y1={y(level)} y2={y(level)}/><text className="graph-axis" x={left-8} y={y(level)+4} textAnchor="end">{level}×</text></g>)}
    {ordered.length>1&&<polyline className="lottery-peak-line" points={line}/>} {ordered.map((row,index)=><circle className={row.peak_multiple>=10?'lottery-peak-point ten':row.peak_multiple>=5?'lottery-peak-point five':row.peak_multiple>=2?'lottery-peak-point two':'lottery-peak-point'} key={row.id} cx={x(index)} cy={y(row.peak_multiple)} r={6}><title>{`${row.symbol} ${row.right} ${row.strike} · ${multiple(row.peak_multiple)} at ${formatEasternTime(row.peak_bid_at)}`}</title></circle>)}
    <text className="graph-axis" x={left} y={height-12}>{formatEasternTime(ordered[0].first_seen_at)}</text><text className="graph-axis" x={width-right} y={height-12} textAnchor="end">{formatEasternTime(ordered[ordered.length-1].first_seen_at)}</text>
  </svg>;
}

function ThresholdGraph({summary}:{summary:LotterySessionSummary}) {
  const below=Math.max(0,summary.contract_count-summary.hit_2x_count);
  const two=Math.max(0,summary.hit_2x_count-summary.hit_5x_count);
  const five=Math.max(0,summary.hit_5x_count-summary.hit_10x_count);
  const ten=summary.hit_10x_count;
  const rows=[['Below 2×',below,'below'],['Reached 2×',two,'two'],['Reached 5×',five,'five'],['Reached 10×',ten,'ten']] as const;
  return <div className="lottery-threshold-graph" role="img" aria-label="Contract peak outcome distribution"><div className="lottery-threshold-stack">{rows.filter(([,count])=>count>0).map(([label,count,key])=><span className={key} key={key} style={{width:`${summary.contract_count?count/summary.contract_count*100:0}%`}} title={`${label}: ${count}`}/>)}</div><div className="lottery-threshold-legend">{rows.map(([label,count,key])=><div key={key}><i className={key}/><span>{label}</span><strong>{count}</strong></div>)}</div></div>;
}

function LotteryLineChart({detail}:{detail:LotteryTrackerDetail}) {
  const points=detail.points;
  if(points.length===0)return <div className="lottery-chart-empty">Waiting for the first saved quote.</div>;
  const width=680,height=260,left=56,right=18,top=20,bottom=42;
  const plotWidth=width-left-right,plotHeight=height-top-bottom;
  const times=points.map(pointTime);
  const minTime=Math.min(...times),maxTime=Math.max(...times);
  const maxValue=Math.max(detail.tracker.entry_cost,...points.map(point=>point.bid_value),1)*1.12;
  const x=(point:LotteryTrackerPoint)=>maxTime===minTime?left+plotWidth/2:left+((pointTime(point)-minTime)/(maxTime-minTime))*plotWidth;
  const y=(value:number)=>top+plotHeight-(value/maxValue)*plotHeight;
  const line=points.map(point=>`${x(point).toFixed(1)},${y(point.bid_value).toFixed(1)}`).join(' ');
  const entryY=y(detail.tracker.entry_cost);
  return <figure className="lottery-line-chart"><figcaption><strong>Minute-by-minute sellable value</strong><span>Entry uses the first qualifying ask; every later point uses the recorded bid.</span></figcaption><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${detail.tracker.symbol} ${detail.tracker.right} ${detail.tracker.strike} sellable option value by scan`}>
    {[0,.25,.5,.75,1].map(level=>{const value=maxValue*level;const lineY=y(value);return <g key={level}><line className="lottery-grid-line" x1={left} x2={width-right} y1={lineY} y2={lineY}/><text className="lottery-axis-label" x={left-8} y={lineY+4} textAnchor="end">${value.toFixed(0)}</text></g>})}<line className="lottery-entry-line" x1={left} x2={width-right} y1={entryY} y2={entryY}/><text className="lottery-entry-label" x={width-right} y={Math.max(top+10,entryY-5)} textAnchor="end">entry {money(detail.tracker.entry_cost)}</text>{points.length>1&&<polyline className="lottery-value-line" points={line}/>} {points.map((point,index)=><circle className={point.is_qualified?'lottery-point qualified':'lottery-point'} key={`${point.observed_at}-${index}`} cx={x(point)} cy={y(point.bid_value)} r={point.is_qualified?4.5:3.5}><title>{`${formatEasternTime(point.observed_at)} · bid ${money(point.bid_value)} · ask ${money(point.ask_value)}`}</title></circle>)}<text className="lottery-axis-label" x={left} y={height-14}>{formatEasternTime(points[0].observed_at)}</text><text className="lottery-axis-label" x={width-right} y={height-14} textAnchor="end">{formatEasternTime(points[points.length-1].observed_at)}</text>
  </svg></figure>;
}

function scenarioText(scenario:LotteryExitScenario):string {
  if(scenario.exit_reason==='NO_QUOTES')return 'No saved bid';
  if(scenario.target_hit)return `target reached ${formatEasternTime(scenario.exit_at)}`;
  return `${scenario.exit_reason==='SESSION_END'?'last saved bid':'current mark'} ${formatEasternTime(scenario.exit_at)}`;
}

function Scenario({label,scenario}:{label:string;scenario:LotteryExitScenario}) {
  return <div><span>{label}</span><strong className={(scenario.return_percent??-1)>=0?'positive-text':'negative-text'}>{multiple(scenario.multiple)}</strong><small>{money(scenario.exit_value)} · {scenarioText(scenario)}</small></div>;
}

function TrackerDetail({detail,onClose}:{detail:LotteryTrackerDetail;onClose:()=>void}) {
  const row=detail.tracker;
  return <section className="lottery-detail" id={`lottery-detail-${row.id}`}><header><div><span className="tag orange">{row.symbol} {row.right.toUpperCase()} {row.strike}</span><h3>{row.option_symbol}</h3></div><button type="button" onClick={onClose}>Close chart</button></header><div className="lottery-summary-grid"><Metric label="Original debit" value={money(row.entry_cost)}/><Metric label="Last saved bid" value={money(row.latest_sellable_value)}/><Metric label="Best observed bid" value={money(row.peak_sellable_value)}/><Metric label="Observed peak" value={multiple(row.peak_multiple)}/><Metric label="Peak time" value={formatEasternTime(row.peak_bid_at)}/><Metric label="Saved minutes" value={row.point_count}/></div><div className="lottery-scenario-grid"><Scenario label="Hold to last" scenario={row.exit_scenarios.hold_to_last}/><Scenario label="Take first 2×" scenario={row.exit_scenarios.take_2x}/><Scenario label="Take first 5×" scenario={row.exit_scenarios.take_5x}/></div><LotteryLineChart detail={detail}/><p className="lottery-method">Observed peak is hindsight, not a fill. Rule outcomes are deterministic one-contract research replays using only saved bids. Paper only.</p></section>;
}

function LotteryLogCard({row,waveSize,onOpen,expanded,loading}:{row:LotteryTrackerSummary;waveSize:number;onOpen:()=>void;expanded:boolean;loading:boolean}) {
  return <article className={`lottery-log-card ${row.status==='ACTIVE'?'active':''}`}><header><div><div className="play-tags"><span>{row.symbol}</span><small>{row.right.toUpperCase()} {row.strike}</small>{row.status==='ACTIVE'&&<small className="live-tag">LIVE</small>}</div><h3>{row.option_symbol}</h3><p>{formatDateOnly(row.trading_date)} · first seen {formatEasternTime(row.first_seen_at)} · {row.point_count} saved minutes</p></div><div className="lottery-peak-callout"><small>Best observed — hindsight</small><strong>{multiple(row.peak_multiple)}</strong><span>{money(row.peak_sellable_value)} at {formatEasternTime(row.peak_bid_at)}</span></div></header><div className="lottery-money-flow"><div><span>Paper debit</span><strong>−{money(row.entry_cost)}</strong><small>first qualifying ask</small></div><b>→</b><Scenario label="Hold to last" scenario={row.exit_scenarios.hold_to_last}/><Scenario label="Take first 2×" scenario={row.exit_scenarios.take_2x}/><Scenario label="Take first 5×" scenario={row.exit_scenarios.take_5x}/></div><footer><span>{waveSize>1?`${waveSize} adjacent strikes entered in this same scanner wave`:'Single contract in this scanner wave'}</span><button className="lottery-chart-button" type="button" aria-expanded={expanded} aria-controls={`lottery-detail-${row.id}`} disabled={loading} onClick={onOpen}>{loading?'Loading…':expanded?'Hide quote path':'View quote path'}</button></footer></article>;
}

export function LotteryLab() {
  const [data,setData]=useState<LotteryTrackerList|null>(null);
  const [selectedDate,setSelectedDate]=useState('');
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [detail,setDetail]=useState<LotteryTrackerDetail|null>(null);
  const [loadingId,setLoadingId]=useState<string|null>(null);
  const [page,setPage]=useState(1);
  const [message,setMessage]=useState('');
  const refresh=useCallback(async(date?:string)=>{try{const result=await getLotteryTrackers(date);setData(result);setSelectedDate(current=>current||result.trading_date);setMessage('')}catch{setMessage('Lottery performance log is temporarily unavailable.')}},[]);
  useEffect(()=>{void refresh(selectedDate||undefined);const timer=window.setInterval(()=>void refresh(selectedDate||undefined),LOTTERY_TRACKER_REFRESH_INTERVAL_MS);return()=>window.clearInterval(timer)},[refresh,selectedDate]);
  useEffect(()=>{if(!selectedId)return;const timer=window.setInterval(()=>void getLotteryTracker(selectedId).then(setDetail).catch(()=>setMessage('Unable to load this quote path.')),LOTTERY_TRACKER_REFRESH_INTERVAL_MS);return()=>window.clearInterval(timer)},[selectedId]);
  const trackers=useMemo(()=>data?.trackers??[],[data]);
  const totalPages=Math.max(1,Math.ceil(trackers.length/PAGE_SIZE));
  const visible=trackers.slice((page-1)*PAGE_SIZE,page*PAGE_SIZE);
  const waveSizes=useMemo(()=>{const counts=new Map<string,number>();trackers.forEach(row=>counts.set(row.entry_wave_id,(counts.get(row.entry_wave_id)??0)+1));return counts},[trackers]);
  const open=async(row:LotteryTrackerSummary)=>{if(selectedId===row.id){setSelectedId(null);setDetail(null);return}setLoadingId(row.id);setMessage('');try{setDetail(await getLotteryTracker(row.id));setSelectedId(row.id)}catch{setMessage('Unable to load this quote path.')}finally{setLoadingId(null)}};
  const chooseDate=(date:string)=>{setSelectedDate(date);setSelectedId(null);setDetail(null);setPage(1)};
  return <section id="lottery" className="lottery-page"><header className="lottery-page-heading"><div><p className="eyebrow">PERMANENT PAPER RESEARCH LOG</p><h2>Lottery Plays</h2><p>{data?`${formatDateOnly(data.trading_date)} · `:''}Every logged contract now separates its best hindsight print from repeatable exit-rule results.</p></div><span>bid-based · paper only</span></header><div className="risk-warning"><strong>Highly speculative. The observed peak is not money you could know to take in real time.</strong><span>Most lottery contracts are expected to expire worthless. The log charges the first ask and values exits at saved bids—never midpoint, last price, or a perfect top.</span></div>
    {data&&<><div className="lottery-log-controls"><label>Session<select aria-label="Lottery log session" value={selectedDate} onChange={event=>chooseDate(event.target.value)}>{data.available_dates.map(date=><option key={date} value={date}>{formatDateOnly(date)}</option>)}</select></label><div><span>Current view</span><strong>{data.summary.contract_count} contracts across {data.summary.entry_wave_count} scanner waves</strong></div></div><div className="headline-metrics lottery-headline"><Metric label="Logged contracts" value={data.summary.contract_count}/><Metric label="Scanner waves" value={data.summary.entry_wave_count}/><Metric label="Reached 2× bid" value={`${data.summary.hit_2x_count} / ${data.summary.contract_count}`}/><Metric label="Best observed" value={multiple(data.summary.best_observed_multiple)}/></div><div className="performance-chart-grid lottery-chart-grid"><section className="graph-panel graph-wide"><header><div><span>ONE CONTRACT PER LOGGED ROW</span><h3>What each exit rule would have returned</h3></div><strong>{money(data.summary.total_entry_cost)} total paper debit</strong></header><RuleComparisonChart rules={data.summary.rule_comparisons} cost={data.summary.total_entry_cost}/><p className="lottery-graph-note">Target rules fall back to the last saved bid when the target is missed. The faded hindsight bar is a ceiling, not an executable rule.</p></section><section className="graph-panel"><header><div><span>PEAK PATH</span><h3>How high each contract printed</h3></div><strong>{multiple(data.summary.best_observed_multiple)} max</strong></header><PeakMultipleChart trackers={trackers}/></section><section className="graph-panel"><header><div><span>OUTCOME MIX</span><h3>Where the peaks topped out</h3></div><strong>{data.summary.hit_10x_count} reached 10×</strong></header><ThresholdGraph summary={data.summary}/></section></div><section className="lottery-log"><header className="play-log-heading"><div><p className="eyebrow">CONTRACT-BY-CONTRACT MONEY FLOW</p><h3>Lottery performance log</h3><p>Each row is permanent and can reopen its complete quote path.</p></div><span>{trackers.length} entries</span></header>{visible.length===0?<div className="lottery-empty"><strong>No lottery contracts logged for this session</strong><span>Choose another saved date above.</span></div>:<div className="lottery-log-grid">{visible.map(row=><LotteryLogCard key={row.id} row={row} waveSize={waveSizes.get(row.entry_wave_id)??1} expanded={selectedId===row.id} loading={loadingId===row.id} onOpen={()=>void open(row)}/>)}</div>}{trackers.length>PAGE_SIZE&&<nav className="pagination" aria-label="Lottery log pages"><button type="button" disabled={page===1} onClick={()=>setPage(value=>Math.max(1,value-1))}>Previous</button><span>Page {page} of {totalPages}</span><button type="button" disabled={page===totalPages} onClick={()=>setPage(value=>Math.min(totalPages,value+1))}>Next</button></nav>}</section><p className="lottery-accounting-note">{data.accounting_note} These are research comparisons, not actual fills or brokerage P/L.</p></>}
    {!data&&!message&&<div className="lottery-empty"><strong>Loading the lottery log…</strong><span>Reading saved contract paths.</span></div>}{message&&<p className="lottery-tracker-message" role="status">{message}</p>}{detail&&selectedId===detail.tracker.id&&<TrackerDetail detail={detail} onClose={()=>{setSelectedId(null);setDetail(null)}}/>}
  </section>;
}
