import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { Performance } from './Performance';
import type { PerformanceResponse, PerformanceSignal } from '../types';

afterEach(()=>{cleanup();vi.restoreAllMocks()});

const signal=(overrides:Partial<PerformanceSignal>):PerformanceSignal=>({signal_id:'sig',source:'LIVE',ticker:'SPY',direction:'CALL',setup_type:'directional-liquidity',strategy_mode:'ONE_MIN_0DTE',strategy_version:'parlay-v1',trading_date:'2026-08-04',triggered_at:'2026-08-04T14:00:00Z',entry_price:100,stop_price:99,target_price:102,exit_reason:'TARGET',result_r:2,result_return_pct:2,initial_risk_points:1,initial_risk_pct:1,mfe_return_pct:2,mae_return_pct:.1,duration_minutes:10,score:90,user_entered:false,option_snapshot:null,strategy_snapshot:{},condition_snapshot:{},conservative_same_candle:false,mfe_r:2,mae_r:.1,...overrides});

test('LIVE metrics ignore migrated UNKNOWN audit rows',async()=>{
  const data:PerformanceResponse={timezone:'America/New_York',underlying_only:true,paper_only:true,metrics:{total_triggered_signals:2,open_signals:0,targets_hit:1,stops_hit:1,timed_exits:0,invalidated_missed:0,win_rate:50,average_r:-49,cumulative_r:-98,profit_factor:.02,maximum_drawdown_r:100,average_duration:10,average_mfe:2,average_mae:50},signals:[signal({signal_id:'live-win',source:'LIVE',ticker:'SPY',exit_reason:'TARGET',result_r:2,mfe_r:2,mae_r:.1}),signal({signal_id:'unknown-loss',source:'UNKNOWN',ticker:'IWN',exit_reason:'STOP',result_r:-100,mfe_r:.1,mae_r:100})]};
  vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}}));
  render(<Performance/>);
  await waitFor(()=>expect(screen.getByText('SPY')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button',{name:'LIVE'}));
  expect(screen.getByText('SPY')).toBeInTheDocument();
  expect(screen.queryByText('IWN')).not.toBeInTheDocument();
  expect(screen.getByText('Triggered').closest('.metric')).toHaveTextContent('1');
  expect(screen.getByText('Win rate %').closest('.metric')).toHaveTextContent('100');
  expect(screen.getByText('Average return %').closest('.metric')).toHaveTextContent('2');
  expect(screen.getByText('Cumulative return %').closest('.metric')).toHaveTextContent('2');
  expect(screen.getByText('Max drawdown %').closest('.metric')).toHaveTextContent('0');
  fireEvent.click(screen.getByRole('button',{name:'R Multiple'}));
  expect(screen.getByText('Average R').closest('.metric')).toHaveTextContent('2');
  fireEvent.click(screen.getByRole('button',{name:'AUDIT'}));
  expect(screen.getByText('IWN')).toBeInTheDocument();
});

test('shows paper option return and timezone-less UTC trigger in Eastern time',async()=>{
  const data:PerformanceResponse={timezone:'America/New_York',underlying_only:false,paper_only:true,metrics:{total_triggered_signals:1,open_signals:0,targets_hit:0,stops_hit:0,timed_exits:1,invalidated_missed:0,win_rate:100,average_r:.1,cumulative_r:.1,profit_factor:null,maximum_drawdown_r:0,average_duration:25,average_mfe:.2,average_mae:.1},signals:[signal({triggered_at:'2026-08-06T13:39:00',exit_reason:'TIMED_EXIT',result_return_pct:165.2174,user_entered:true,return_basis:'PAPER_OPTION',paper_entry_option_price:.23,paper_exit_option_price:.61})]};
  vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}}));
  render(<Performance/>);
  await waitFor(()=>expect(screen.getByText(/165\.22%/)).toBeInTheDocument());
  expect(screen.getByText(/Aug 6, 2026, 9:39 AM EDT/)).toBeInTheDocument();
  expect(screen.getByText(/PAPER · OPTION/)).toBeInTheDocument();
});
