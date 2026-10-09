import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {Performance} from './Performance';
import type {PerformanceMetrics,PerformanceResponse,PerformanceSignal} from '../types';

afterEach(()=>{cleanup();vi.restoreAllMocks()});

const signal=(overrides:Partial<PerformanceSignal>):PerformanceSignal=>({
  signal_id:'sig',source:'LIVE',ticker:'SPY',direction:'CALL',setup_type:'directional-liquidity',
  strategy_mode:'ONE_MIN_0DTE',strategy_version:'parlay-v1',trading_date:'2026-08-04',
  triggered_at:'2026-08-04T14:00:00Z',entry_price:100,stop_price:99,target_price:102,
  exit_at:'2026-08-04T14:10:00Z',exit_price:102,
  exit_reason:'TARGET',result_r:2,result_return_pct:2,initial_risk_points:1,initial_risk_pct:1,
  mfe_return_pct:2,mae_return_pct:.1,duration_minutes:10,score:90,user_entered:false,
  analytics_eligible:true,analytics_exclusion_reason:null,option_snapshot:null,strategy_snapshot:{},
  condition_snapshot:{},conservative_same_candle:false,mfe_r:2,mae_r:.1,
  automated_option_shadow:null,...overrides,
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
  option_shadow_metrics:{tracked_positions:0,closed_with_quote:0,quote_gaps:0,active_positions:0,
    exit_pending:0,untracked_selected_positions:signals.length,quote_coverage_percent:0,wins:0,losses:0,
    cumulative_pnl_dollars:0,average_pnl_dollars:0,average_return_percent:0,
    entry_basis:'Ask at automated BUY',exit_basis:'First verified bid after underlying exit',forward_only:true,
    headline_metrics:false,fees_modeled:false,additional_slippage_modeled:false,paper_only:true},
  execution_cost_analysis:{closed_with_quote:1,
    observed:{pnl_dollars:-50,average_pnl_dollars:-50,wins:0,losses:1,breakeven:0},
    net_after_costs:{pnl_dollars:-51,average_pnl_dollars:-51,wins:0,losses:1,breakeven:0},
    stress:{pnl_dollars:-53,average_pnl_dollars:-53,wins:0,losses:1,breakeven:0},
    assumptions:{commission_per_contract_dollars:1,additional_fees_per_contract_dollars:0,
      extra_slippage_per_side_option_dollars:.01,round_trip_fixed_cost_dollars:1,
      observed_fill_basis:'Verified entry ask to verified exit bid',
      stress_fill_basis:'Entry ask plus slippage; exit bid minus slippage'},
    by_ticker:[{label:'SPY',closed_with_quote:1,observed_pnl_dollars:-50,net_pnl_dollars:-51,stress_pnl_dollars:-53}],
    by_exit_reason:[{label:'TIMED_EXIT',closed_with_quote:1,observed_pnl_dollars:-50,net_pnl_dollars:-51,stress_pnl_dollars:-53}],
    forward_only:true,historical_records_changed:false,paper_only:true},
  paper_money_tracker:{starting_cash_dollars:25000,quantity_per_entry:1,entry_basis:'One contract at verified ask',
    exit_basis:'First verified bid after underlying exit',open_value_basis:'Original debit; unrealized option value is not estimated',
    fees_modeled:false,additional_slippage_modeled:false,forward_only:true,historical_records_changed:false,paper_only:true,
    portfolios:[
      {key:'ALL',label:'All tracked tickers',starting_cash_dollars:25000,cash_available_dollars:24950,
        capital_at_cost_dollars:0,book_equity_dollars:24950,realized_pnl_dollars:-50,return_percent:-.2,
        maximum_drawdown_dollars:50,maximum_drawdown_percent:.2,total_entry_debits_dollars:100,
        positions_taken:1,closed_positions:1,active_positions:0,quote_gaps:0,exit_pending:0,
        skipped_insufficient_cash:0,wins:0,losses:1,daily:[{trading_date:'2026-08-04',entries:1,
          closed:1,skipped:0,daily_realized_pnl_dollars:-50,cash_dollars:24950,
          capital_at_cost_dollars:0,book_equity_dollars:24950,cumulative_realized_pnl_dollars:-50}]},
      {key:'CORE',label:'Core only · SPY / QQQ / IWM',starting_cash_dollars:25000,cash_available_dollars:25030,
        capital_at_cost_dollars:0,book_equity_dollars:25030,realized_pnl_dollars:30,return_percent:.12,
        maximum_drawdown_dollars:0,maximum_drawdown_percent:0,total_entry_debits_dollars:45,
        positions_taken:1,closed_positions:1,active_positions:0,quote_gaps:0,exit_pending:0,
        skipped_insufficient_cash:0,wins:1,losses:0,daily:[{trading_date:'2026-08-04',entries:1,
          closed:1,skipped:0,daily_realized_pnl_dollars:30,cash_dollars:25030,
          capital_at_cost_dollars:0,book_equity_dollars:25030,cumulative_realized_pnl_dollars:30}]},
    ]},
  research_breakdowns:{cohorts:[
    {key:'CORE',label:'Core index cohort',tickers:['SPY','QQQ','IWM'],selected_plays:selected.total_triggered_signals,resolved_plays:selected.resolved_signals,total_r:selected.cumulative_r,average_r:selected.average_r,win_rate:selected.win_rate,profit_factor:selected.profit_factor,maximum_drawdown_r:selected.maximum_drawdown_r},
    {key:'EXPERIMENTAL',label:'Experimental universe',tickers:[],selected_plays:0,resolved_plays:0,total_r:0,average_r:0,win_rate:0,profit_factor:null,maximum_drawdown_r:0},
  ],option_shadow_by_ticker:[],option_shadow_by_exit_reason:[],cohort_definition:'Core = SPY, QQQ, IWM; Experimental = every other configured ticker.',historical_records_changed:false},
  chart_data:{daily:[{trading_date:'2026-08-04',result_r:2,return_pct:2,cumulative_r:2,
    cumulative_return_pct:2,resolved:1,wins:1,losses:0,option_pnl_dollars:0,
    cumulative_option_pnl_dollars:0,option_closed:0}],outcomes:[{outcome:'TARGET',count:signals.length}]},
  market_movement:{resolved_with_prices:1,average_directional_move_pct:2,positive_direction_rate:100,
    cumulative_directional_move_pct:2,net_raw_underlying_move_pct:2,average_raw_underlying_move_pct:2,
    daily:[{trading_date:'2026-08-04',raw_move_pct:2,directional_move_pct:2,
      cumulative_raw_move_pct:2,cumulative_directional_move_pct:2,resolved:1}]},
  pagination:{page:1,page_size:25,total_items:signals.length,total_pages:1},
  scope:{source:'LIVE',strategy_mode:strategy,user_entered:false,deduplication:'FIRST_BUY_PER_TICKER_DAY'},
});

function mockResponses(zeroDte:PerformanceResponse,structured:PerformanceResponse){
  vi.spyOn(globalThis,'fetch').mockImplementation(input=>Promise.resolve(new Response(JSON.stringify(
    String(input).includes('STRUCTURED_INTRADAY')?structured:zeroDte
  ),{status:200,headers:{'Content-Type':'application/json'}})));
}

test('shows visual strategy graphs and expandable play cards',async()=>{
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
  await waitFor(()=>expect(screen.getByLabelText('Cumulative Strategy R by trading day')).toBeInTheDocument());
  expect(vi.mocked(globalThis.fetch).mock.calls.some(([input])=>String(input).includes('paper_starting_cash=2000'))).toBe(true);
  const strategyMetrics=screen.getByRole('region',{name:'Strategy Performance metrics'});
  expect(within(strategyMetrics).getByText('Total Selected Plays').closest('.metric')).toHaveTextContent('2');
  expect(within(strategyMetrics).getByText('Total R').closest('.metric')).toHaveTextContent('2');
  expect(within(strategyMetrics).getByText('Open Plays')).toBeInTheDocument();
  expect(screen.getByText('R = strategy performance normalized by trade risk')).toBeInTheDocument();
  expect(screen.getByLabelText('Play outcome distribution')).toBeInTheDocument();
  expect(screen.getByRole('region',{name:'Core and experimental cohort comparison'})).toBeInTheDocument();
  const execution=screen.getByRole('region',{name:'Strategy and execution comparison'});
  expect(within(execution).getByText('Does the underlying edge survive option execution?')).toBeInTheDocument();
  expect(within(execution).getByText('After fixed costs').closest('article')).toHaveTextContent('-$51.00');
  expect(within(execution).getByText(/immutable marks/)).toBeInTheDocument();
  expect(vi.mocked(globalThis.fetch).mock.calls.some(([input])=>String(input).includes('commission_per_contract=1'))).toBe(true);
  fireEvent.click(within(execution).getByRole('button',{name:'2¢'}));
  await waitFor(()=>expect(vi.mocked(globalThis.fetch).mock.calls.some(([input])=>String(input).includes('extra_slippage_per_side=0.02'))).toBe(true));
  const money=screen.getByRole('region',{name:'Paper money tracker'});
  expect(within(money).getByText('What would the account balance look like?')).toBeInTheDocument();
  expect(within(money).getByLabelText('Paper account equity comparison')).toBeInTheDocument();
  expect(within(money).getAllByText('Core only · SPY / QQQ / IWM')).toHaveLength(2);
  expect(within(money).getByText(/Open or unpriced positions are carried at original cost/)).toBeInTheDocument();
  fireEvent.click(within(money).getByRole('button',{name:'$250.00'}));
  await waitFor(()=>expect(vi.mocked(globalThis.fetch).mock.calls.some(([input])=>String(input).includes('paper_starting_cash=250'))).toBe(true));
  fireEvent.click(screen.getAllByRole('button',{name:'See play details'})[0]);
  expect(screen.getByText('Technical audit data')).toBeInTheDocument();
  expect(screen.getByText(/Raw repeated alerts remain visible only in aggregate counts/)).toBeInTheDocument();
});

test('keeps Strategy R primary and distinguishes directional from raw put movement',async()=>{
  const put=signal({signal_id:'put',direction:'PUT',entry_price:100,stop_price:101,target_price:99,
    exit_price:99,result_r:1,result_return_pct:1});
  const data=response('ONE_MIN_0DTE',[put],metrics({average_r:1,cumulative_r:1}));
  data.chart_data.daily[0].result_r=1;
  data.chart_data.daily[0].cumulative_r=1;
  data.market_movement={resolved_with_prices:1,average_directional_move_pct:1,
    positive_direction_rate:100,cumulative_directional_move_pct:1,
    net_raw_underlying_move_pct:-1,average_raw_underlying_move_pct:-1,
    daily:[{trading_date:'2026-08-04',raw_move_pct:-1,directional_move_pct:1,
      cumulative_raw_move_pct:-1,cumulative_directional_move_pct:1,resolved:1}]};
  mockResponses(data,response('STRUCTURED_INTRADAY',[]));
  render(<Performance/>);
  await waitFor(()=>expect(screen.getByLabelText('Cumulative Strategy R by trading day')).toBeInTheDocument());
  expect(screen.getByRole('button',{name:'Strategy R'})).toHaveAttribute('aria-pressed','true');
  expect(screen.getByText('Is the strategy growing?')).toBeInTheDocument();
  expect(within(screen.getByRole('region',{name:'Strategy Performance metrics'})).getByText('Total R').closest('.metric')).toHaveTextContent('+1.00R');

  fireEvent.click(screen.getByRole('button',{name:'Directional Move'}));
  expect(screen.getByLabelText('Cumulative directional underlying move by trading day')).toBeInTheDocument();
  expect(screen.getByText('Did Parlay correctly predict the direction of the underlying?')).toBeInTheDocument();
  const directional=screen.getByRole('region',{name:'Market Movement metrics'});
  expect(within(directional).getByText('Average Directional Move').closest('.metric')).toHaveTextContent('+1.000%');
  expect(within(directional).getByText('Positive Direction Rate').closest('.metric')).toHaveTextContent('100%');
  expect(within(directional).getByText('Cumulative Directional Move').closest('.metric')).toHaveTextContent('+1.00%');
  expect(screen.getByText('Directional move').closest('div')).toHaveTextContent('+1.00%');

  fireEvent.click(screen.getByRole('button',{name:'Raw Underlying'}));
  expect(screen.getByLabelText('Cumulative raw underlying move by trading day')).toBeInTheDocument();
  expect(screen.getByText('Raw Underlying Movement')).toBeInTheDocument();
  const raw=screen.getByRole('region',{name:'Market Movement metrics'});
  expect(within(raw).getByText('Net Raw Underlying Move').closest('.metric')).toHaveTextContent('-1.00%');
  expect(within(raw).getByText('Avg. Raw Underlying Move').closest('.metric')).toHaveTextContent('-1.000%');
  expect(screen.getByText("Shows price movement of the underlying, not the option trade's return. Calls and puts are not direction-adjusted in this view.")).toBeInTheDocument();
  expect(screen.getByText('Raw underlying move').closest('div')).toHaveTextContent('-1.00%');
  expect(screen.queryByText('Total Underlying %')).not.toBeInTheDocument();
});

test('keeps structured 5-14 DTE results in a separate dataset',async()=>{
  const zero=response('ONE_MIN_0DTE',[signal({ticker:'SPY'})]);
  const structuredSignal=signal({ticker:'QQQ',strategy_mode:'STRUCTURED_INTRADAY'});
  const structured=response('STRUCTURED_INTRADAY',[structuredSignal]);
  mockResponses(zero,structured);
  render(<Performance/>);
  await waitFor(()=>expect(screen.getByText(/SPY CALL/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button',{name:'Structured 5–14 DTE'}));
  await waitFor(()=>expect(screen.getByText(/QQQ CALL/)).toBeInTheDocument());
  expect(screen.queryByText(/SPY CALL/)).not.toBeInTheDocument();
  expect(screen.getAllByText(/Structured Intraday · 5–14 DTE/).length).toBeGreaterThan(0);
});

test('requests the next server-side performance page',async()=>{
  const first=response('ONE_MIN_0DTE',[signal({ticker:'SPY'})]);
  first.pagination={page:1,page_size:25,total_items:26,total_pages:2};
  const second=response('ONE_MIN_0DTE',[signal({ticker:'QQQ',signal_id:'page-2'})]);
  second.pagination={page:2,page_size:25,total_items:26,total_pages:2};
  vi.spyOn(globalThis,'fetch').mockImplementation(input=>Promise.resolve(new Response(JSON.stringify(
    String(input).includes('page=2')?second:first
  ),{status:200,headers:{'Content-Type':'application/json'}})));
  render(<Performance/>);
  await waitFor(()=>expect(screen.getByText(/SPY CALL/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button',{name:'Next →'}));
  await waitFor(()=>expect(screen.getByText(/QQQ CALL/)).toBeInTheDocument());
  expect(screen.queryByText(/SPY CALL/)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Performance log pages')).toHaveTextContent('Page 2 of 2');
});
