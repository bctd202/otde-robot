import {useEffect,useState} from 'react';
import {getBacktests,startBacktest} from '../api/client';
import type {BacktestRun} from '../types';

const evidenceLabel=(run:BacktestRun)=>run.strategy_snapshot?.evidence_mode==='UNDERLYING_ONLY'?
  'Underlying-only replay · option eligibility unavailable':run.strategy_snapshot?.result_model_version?
  'Archived option eligibility checked · R remains an underlying benchmark':'Legacy replay · original assumptions retained';

export function BacktestLab(){
  const today=new Date().toLocaleDateString('en-CA',{timeZone:'America/New_York'});
  const [start,setStart]=useState(today),[end,setEnd]=useState(today),[tickers,setTickers]=useState('SPY,QQQ');
  const [runs,setRuns]=useState<BacktestRun[]>([]),[running,setRunning]=useState(false),[error,setError]=useState('');
  useEffect(()=>{void getBacktests().then(value=>{if(Array.isArray(value))setRuns(current=>
    [...current,...value.filter(run=>!current.some(saved=>saved.id===run.id))])})
    .catch(()=>setError('Saved replay history is unavailable.'))},[]);
  async function submit(){
    if(running)return;
    setRunning(true);setError('');
    try{
      const run=await startBacktest(start,end,tickers.split(',').map(v=>v.trim().toUpperCase()).filter(Boolean));
      setRuns(old=>[run,...old.filter(item=>item.id!==run.id)]);
    }catch(reason){setError(reason instanceof Error?reason.message:'Backtest failed')}
    finally{setRunning(false)}
  }
  const latest=runs[0],diagnostics=latest?.strategy_snapshot?.diagnostics;
  return <section id="backtest-lab" className="backtest-page">
    <p className="eyebrow">Chronological price replay · explicit evidence limits</p><h2>Backtest Lab</h2>
    <p>Entries use the next consecutive same-session bar’s open. Replay can verify the live BUY rules only with archived option quotes that pass the full entry gate. Stock candles alone produce underlying-only observations, not option trades or portfolio returns.</p>
    <div className="backtest-controls">
      <label>Start<input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label>
      <label>End<input type="date" value={end} onChange={e=>setEnd(e.target.value)}/></label>
      <label>Tickers<input value={tickers} onChange={e=>setTickers(e.target.value)}/></label>
      <button disabled={running} onClick={()=>void submit()}>{running?'Running…':'Run Backtest'}</button>
    </div>
    {error&&<p role="alert">{error}</p>}
    {latest&&<article className="run-result">
      <h3>{latest.status} · {latest.id.slice(0,8)}</h3><strong>{evidenceLabel(latest)}</strong>
      <p>Requested {latest.requested_start}–{latest.requested_end} · Available {latest.actual_start??'unavailable'}–{latest.actual_end??'unavailable'}</p>
      <p>History available: {latest.tickers.filter(t=>!latest.failures[t]).join(', ')||'None'} · Failed: {Object.keys(latest.failures).join(', ')||'None'}</p>
      {diagnostics&&<p>{diagnostics.verified_buy_entries} BUY-qualified setups · {diagnostics.underlying_only_entries} underlying-only observations · {diagnostics.rejected_live_gate} rejected entry checks. These are not broker fills.</p>}
      {latest.warnings.map(w=><p key={w}>{w}</p>)}
    </article>}
    <h3>Saved run history</h3>{runs.map(run=><div className="run-history" key={run.id}>
      <b>{run.status}</b><span>{run.requested_start} – {run.requested_end}</span><span>{run.tickers.join(', ')}</span>
      <small>{evidenceLabel(run)}</small>
    </div>)}
  </section>;
}
