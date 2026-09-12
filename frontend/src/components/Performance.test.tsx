import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {Performance} from './Performance';
import type {PerformanceMetrics,PerformanceResponse,PerformanceSignal} from '../types';

afterEach(()=>{cleanup();vi.restoreAllMocks()});

const signal=(overrides:Partial<PerformanceSignal>):PerformanceSignal=>({
  signal_id:'sig',source:'LIVE',ticker:'SPY',direction:'CALL',setup_type:'directional-liquidity',
  strategy_mode:'ONE_MIN_0DTE',strategy_version:'parlay-v1',trading_date:'2026-08-04',
  triggered_at:'2026-08-04T14:00:00Z',entry_price:100,stop_price:99,target_price:102,
  exit_reason:'TARGET',result_r:2,result_return_pct:2,initial_risk_points:1,initial_risk_pct:1,
  mfe_return_pct:2,mae_return_pct:.1,duration_minutes:10,score:90,user_entered:false,
  analytics_eligible:true,analytics_exclusion_reason:null,option_snapshot:null,strategy_snapshot:{},
  condition_snapshot:{},conservative_same_candle:false,mfe_r:2,mae_r:.1,...overrides,
});

const metrics=(overrides:Partial<PerformanceMetrics>={}):PerformanceMetrics=>({
  total_triggered_signals:1,resolved_signals:1,open_signals:0,targets_hit:1,stops_hit:0,
  timed_exits:0,invalidated_missed:0,data_gap_signals:0,quality_exclusions:0,wins:1,losses:0,
  breakeven:0,win_rate:100,average_r:2,cumulative_r:2,profit_factor:null,average_win_r:2,
  average_loss_r:0,maximum_drawdown_r:0,exposure_ticker_days:1,exposure_minutes:10,
  average_duration:10,average_mfe:2,average_mae:.1,average_return_pct:2,cumulative_return_pct:2,
  maximum_drawdown_pct:0,...overrides,
});

const response=(strategy:'ONE_MIN_0DTE'|'STRUCTURED_INTRADAY',signals:PerformanceSignal[],
  selected:PerformanceMetrics=metrics(),raw:PerformanceMetrics=selected):PerformanceResponse=>({
  timezone:'America/New_York',underlying_only:true,paper_only:true,metrics:selected,raw_metrics:raw,signals,
  scope:{source:'LIVE',strategy_mode:strategy,user_entered:false,deduplication:'FIRST_BUY_PER_TICKER_DAY'},
});

function mockResponses(zeroDte:PerformanceResponse,structured:PerformanceResponse){
  vi.spyOn(globalThis,'fetch').mockImplementation(input=>Promise.resolve(new Response(JSON.stringify(
    String(input).includes('STRUCTURED_INTRADAY')?structured:zeroDte
  ),{status:200,headers:{'Content-Type':'application/json'}})));
}

test('defaults to auto-only true-0DTE deduplicated metrics and exposes exclusions',async()=>{
  const excluded=signal({signal_id:'excluded',ticker:'IWM',exit_reason:'TARGET',result_r:50,
    analytics_eligible:false,analytics_exclusion_reason:'CROSS_SESSION_EXIT'});
  const zero=response('ONE_MIN_0DTE',[signal({signal_id:'selected'}),excluded],
    metrics({total_triggered_signals:2,quality_exclusions:1}),
    metrics({total_triggered_signals:7,cumulative_r:-4}));
  const structured=response('STRUCTURED_INTRADAY',[],metrics({total_triggered_signals:0,resolved_signals:0,
    targets_hit:0,wins:0,win_rate:0,average_r:0,cumulative_r:0,average_win_r:0,
    exposure_ticker_days:0,exposure_minutes:0,average_duration:0,average_mfe:0,average_mae:0,
    average_return_pct:0,cumulative_return_pct:0}),metrics({total_triggered_signals:0,resolved_signals:0,
    targets_hit:0,wins:0,win_rate:0,average_r:0,cumulative_r:0,average_win_r:0,
    exposure_ticker_days:0,exposure_minutes:0,average_duration:0,average_mfe:0,average_mae:0,
    average_return_pct:0,cumulative_return_pct:0}));
  mockResponses(zero,structured);
  render(<Performance/>);
  await waitFor(()=>expect(screen.getByText(/7 raw BUY rows/)).toBeInTheDocument());
  expect(screen.getByText(/Manual positions and backtests are excluded/)).toBeInTheDocument();
  expect(screen.getByText('Selected positions').closest('.metric')).toHaveTextContent('2');
  expect(screen.getByText('Cumulative R').closest('.metric')).toHaveTextContent('2');
  expect(screen.queryByRole('button',{name:'PAPER'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'EXCLUDED'}));
  expect(screen.getByText('IWM')).toBeInTheDocument();
  expect(screen.queryByText('SPY')).not.toBeInTheDocument();
  expect(screen.getByText(/EXCLUDED: CROSS SESSION EXIT/)).toBeInTheDocument();
});

test('keeps structured 5-14 DTE results in a separate dataset',async()=>{
  const zero=response('ONE_MIN_0DTE',[signal({ticker:'SPY'})]);
  const structuredSignal=signal({ticker:'QQQ',strategy_mode:'STRUCTURED_INTRADAY'});
  const structured=response('STRUCTURED_INTRADAY',[structuredSignal]);
  mockResponses(zero,structured);
  render(<Performance/>);
  await waitFor(()=>expect(screen.getByText('SPY')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button',{name:'Structured 5–14 DTE'}));
  expect(screen.getByText('QQQ')).toBeInTheDocument();
  expect(screen.queryByText('SPY')).not.toBeInTheDocument();
  expect(screen.getAllByText(/Structured Intraday · 5–14 DTE/).length).toBeGreaterThan(0);
});
