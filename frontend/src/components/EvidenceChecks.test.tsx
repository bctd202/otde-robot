import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,test} from 'vitest';
import {CollectionChecks,ShadowEvidenceChecks} from './EvidenceChecks';

afterEach(cleanup);
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
