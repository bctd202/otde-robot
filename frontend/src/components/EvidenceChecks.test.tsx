import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,test} from 'vitest';
import {CollectionChecks,ShadowEvidenceChecks} from './EvidenceChecks';

afterEach(cleanup);
test('ticker inputs are distinct from saved evaluations and retain missing candles',()=>{
  render(<CollectionChecks evidence={{status:'CLOSED',has_coverage_gaps:true,basis:'Saved minutes',sessions:[{
    date:'2026-10-30',expected_minutes:390,observed_minutes:389,missing_minutes:1,coverage_percent:99.7,complete_session:true,
    input_evidence_started_at:'2026-10-30T13:30:00Z',input_basis:'Actual cached candles.',
    input_coverage:[{symbol:'USO',valid_minutes:64,expected_minutes:390}]}]}}/>);
  expect(screen.getByText('USO: 64/390 valid minute inputs')).toBeInTheDocument();
  expect(screen.getByText('389/390 minutes · 99.7%')).toBeInTheDocument();
});
test('scan timings explain slow work without inventing historical measurements',()=>{
  const evidence={status:'CLOSED' as const,has_coverage_gaps:true,basis:'Saved minutes',sessions:[],
    scan_timing:{measured_scans:2,window_scans:3,over_minute_scans:1,p95_seconds:70,
      latest_at:'2026-10-27T14:00:00Z',latest_phases_ms:{lotto:40000},basis:'Measured work, not every cause of missing scans.'}};
  const {rerender}=render(<CollectionChecks evidence={evidence}/>);
  expect(screen.getByText(/2 measured scans.*70s.*1 took/)).toBeInTheDocument();
  expect(screen.getByText('lotto: 40.0s')).toBeInTheDocument();
  rerender(<CollectionChecks evidence={{...evidence,scan_timing:{...evidence.scan_timing,measured_scans:0,p95_seconds:null}}}/>);
  expect(screen.getByText(/No measured scans yet/)).toBeInTheDocument();
  expect(screen.queryByText(/95% finished/)).not.toBeInTheDocument();
});
test('closed market still exposes missed sessions without claiming active failure',()=>{
  render(<CollectionChecks evidence={{status:'CLOSED',has_coverage_gaps:true,basis:'Saved evaluation minutes',sessions:[{date:'2026-10-23',expected_minutes:390,observed_minutes:0,missing_minutes:390,coverage_percent:0,complete_session:true}]}}/>);
  expect(screen.getByText(/Scanner sleeping.*Coverage gaps/)).toBeInTheDocument();
  expect(screen.getByText('0/390 minutes · 0%')).toBeInTheDocument();
});
test('stale data is not a connected-server success',()=>{
  render(<CollectionChecks evidence={{status:'STALE',has_coverage_gaps:false,basis:'Saved minutes',sessions:[]}}/>);
  expect(screen.getByText('Scanner data overdue')).toBeInTheDocument();
});
test('empty option audit does not invent profits',()=>{
  render(<ShadowEvidenceChecks audit={{quoted_trades:0,flagged_trades:0,best_entry_day:null,best_day_pnl_dollars:null,without_best_day_pnl_dollars:null,daily:[],flagged_examples:[],basis:'Gross quotes',historical_records_changed:false}}/>);
  expect(screen.getByText('No quoted exits to audit yet.')).toBeInTheDocument();
});
test('concentration diagnostic preserves gross-result caveat',()=>{
  render(<ShadowEvidenceChecks audit={{quoted_trades:2,flagged_trades:1,best_entry_day:'2026-10-16',best_day_pnl_dollars:500,without_best_day_pnl_dollars:-50,daily:[{date:'2026-10-16',pnl_dollars:500}],flagged_examples:[],basis:'Gross quotes',historical_records_changed:false}}/>);
  expect(screen.getByText('-$50.00')).toBeInTheDocument();
  expect(screen.getByText(/All trades remain in the totals/)).toBeInTheDocument();
});
