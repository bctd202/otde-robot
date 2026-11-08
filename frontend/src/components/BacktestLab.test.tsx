import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {BacktestLab} from './BacktestLab';
import {getBacktests,startBacktest} from '../api/client';
import type {BacktestRun} from '../types';

vi.mock('../api/client',()=>({getBacktests:vi.fn(),startBacktest:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks()});
const run:BacktestRun={id:'sample-run',requested_start:'2026-11-02',requested_end:'2026-11-02',
  actual_start:'2026-11-02',actual_end:'2026-11-02',tickers:['SPY'],status:'COMPLETED',warnings:[],failures:{},
  started_at:'2026-11-07T12:00:00Z',completed_at:'2026-11-07T12:00:01Z'};

test('completed underlying-only replay is never presented as broker fills or full live qualification',async()=>{
  vi.mocked(getBacktests).mockResolvedValue([{...run,strategy_snapshot:{evidence_mode:'UNDERLYING_ONLY',
    result_model_version:'post-confirmation-quote-v1',diagnostics:{verified_buy_entries:0,
      underlying_only_entries:4,rejected_live_gate:2,input_gaps:1}}}]);
  render(<BacktestLab/>);
  expect((await screen.findAllByText('Underlying-only replay · option eligibility unavailable')).length).toBe(2);
  expect(screen.getByText(/0 BUY-qualified setups · 4 underlying-only observations/)).toBeVisible();
  expect(screen.getByText(/These are not broker fills/)).toBeVisible();
});

test('old saved runs retain a visible legacy-assumptions label',async()=>{
  vi.mocked(getBacktests).mockResolvedValue([run]);render(<BacktestLab/>);
  expect((await screen.findAllByText('Legacy replay · original assumptions retained')).length).toBe(2);
});

test('new replay uses the existing endpoint and preserves saved run history',async()=>{
  vi.mocked(getBacktests).mockResolvedValue([run]);
  vi.mocked(startBacktest).mockResolvedValue({...run,id:'new-run',strategy_snapshot:{
    result_model_version:'post-confirmation-quote-v1',evidence_mode:'ARCHIVED_OPTION_GATE'}});
  render(<BacktestLab/>);await screen.findByText('Saved run history');
  fireEvent.click(screen.getByRole('button',{name:'Run Backtest'}));
  expect((await screen.findAllByText('Archived option eligibility checked · R remains an underlying benchmark')).length).toBe(2);
  expect(startBacktest).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Legacy replay · original assumptions retained')).toBeVisible();
});
