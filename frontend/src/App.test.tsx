import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {App,PARLAY_REFRESH_INTERVAL_MS,stabilizeCandidateOrder} from './main';
import type {LotteryTrackerList,ParlayCandidate,ParlayResponse,PerformanceMetrics,PerformanceResponse} from './types';

afterEach(()=>{cleanup();vi.restoreAllMocks()});

const providerStatus={provider:'tradier',mode:'live',status:'healthy',delay_seconds:0,latest_timestamp:'2026-09-11T14:00:00-04:00',message:'Live Tradier market data; paper research only.'};
const board:ParlayResponse={provider_status:providerStatus,universe:['SPY'],scanner_health:{candidate_count:0,unavailable_candidate_count:0,provider_status:'healthy',engine_status:'running'},paper_only:true,candidates:[]};
const emptyMetrics:PerformanceMetrics={total_triggered_signals:0,resolved_signals:0,open_signals:0,targets_hit:0,stops_hit:0,timed_exits:0,invalidated_missed:0,data_gap_signals:0,quality_exclusions:0,wins:0,losses:0,breakeven:0,win_rate:0,average_r:0,cumulative_r:0,profit_factor:null,average_win_r:0,average_loss_r:0,maximum_drawdown_r:0,exposure_ticker_days:0,exposure_minutes:0,average_duration:0,average_mfe:0,average_mae:0,average_return_pct:0,cumulative_return_pct:0,maximum_drawdown_pct:0};
const performance:PerformanceResponse={metrics:emptyMetrics,raw_metrics:emptyMetrics,option_shadow_metrics:{tracked_positions:0,closed_with_quote:0,quote_gaps:0,active_positions:0,exit_pending:0,untracked_selected_positions:0,quote_coverage_percent:0,wins:0,losses:0,cumulative_pnl_dollars:0,average_pnl_dollars:0,average_return_percent:0,entry_basis:'Ask at automated BUY',exit_basis:'First verified bid after underlying exit',forward_only:true,headline_metrics:false,fees_modeled:false,additional_slippage_modeled:false,paper_only:true},chart_data:{daily:[],outcomes:[]},market_movement:{resolved_with_prices:0,average_directional_move_pct:0,positive_direction_rate:0,cumulative_directional_move_pct:0,net_raw_underlying_move_pct:0,average_raw_underlying_move_pct:0,daily:[]},pagination:{page:1,page_size:25,total_items:0,total_pages:1},signals:[],scope:{source:'LIVE',strategy_mode:'ONE_MIN_0DTE',user_entered:false,deduplication:'FIRST_BUY_PER_TICKER_DAY'},timezone:'America/New_York',underlying_only:true,paper_only:true};
const lottery:LotteryTrackerList={trading_date:'2026-09-11',available_dates:['2026-09-11'],summary:{contract_count:0,entry_wave_count:0,total_entry_cost:0,hit_2x_count:0,hit_5x_count:0,hit_10x_count:0,best_observed_multiple:0,rule_comparisons:[]},trackers:[],entry_basis:'First qualifying ask',performance_basis:'Subsequent sellable bid',accounting_note:'Adjacent strikes are correlated.',paper_only:true};

function response(body:unknown){return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}})}

function mockApplication(){
  const requests:string[]=[];
  vi.spyOn(globalThis,'fetch').mockImplementation(async input=>{
    const url=String(input);requests.push(url);
    if(url.includes('/parlays'))return response(board);
    if(url.includes('/paper-positions'))return response({positions:[],paper_only:true});
    if(url.includes('/signal-alerts'))return response({alerts:[],latest_id:0,paper_only:true});
    if(url.includes('/daily-watch'))return response({trading_date:'2026-09-11',symbols:[],slots_used:0,slot_limit:2});
    if(url.includes('/lottery-trackers'))return response(lottery);
    if(url.includes('/performance'))return response(performance);
    if(url.includes('/backtests'))return response([]);
    return new Response('not found',{status:404});
  });
  return requests;
}

test('renders the focused board and visual history without legacy dashboard calls',async()=>{
  const requests=mockApplication();
  render(<App/>);
  await waitFor(()=>expect(screen.getByText('NO QUALIFIED PARLAYS RIGHT NOW')).toBeInTheDocument());
  expect(screen.getByRole('link',{name:'Lottery Plays'})).toBeInTheDocument();
  expect(screen.getByRole('heading',{name:'Lottery Plays'})).toBeInTheDocument();
  expect(screen.getByRole('heading',{name:'Play History & Performance'})).toBeInTheDocument();
  expect(screen.getByText(/Most lottery contracts are expected to expire worthless/)).toBeInTheDocument();
  expect(screen.queryByText('Market Context')).not.toBeInTheDocument();
  expect(screen.queryByText('Chart Workspace')).not.toBeInTheDocument();
  expect(screen.queryByText(/Signal Journal/)).not.toBeInTheDocument();
  expect(screen.queryByText('Seeded Paper Analytics')).not.toBeInTheDocument();
  expect(requests.some(url=>/dashboard|journal|analytics/.test(url))).toBe(false);
});

test('polls the server-owned Parlay cache every 15 seconds',()=>{
  const interval=vi.spyOn(window,'setInterval');mockApplication();render(<App/>);
  expect(PARLAY_REFRESH_INTERVAL_MS).toBe(15_000);
  expect(interval).toHaveBeenCalledWith(expect.any(Function),15_000);
});

test('manual refresh retains the board, prevents overlap, and marks a failed scan stale',async()=>{
  const interval=vi.spyOn(window,'setInterval');
  let parlayCalls=0;let rejectRefresh:((reason?:unknown)=>void)|undefined;
  vi.spyOn(globalThis,'fetch').mockImplementation(async input=>{
    const url=String(input);
    if(url.includes('/parlays')){parlayCalls+=1;if(parlayCalls>1)return new Promise<Response>((_,reject)=>{rejectRefresh=reject});return response(board)}
    if(url.includes('/paper-positions'))return response({positions:[],paper_only:true});
    if(url.includes('/signal-alerts'))return response({alerts:[],latest_id:0,paper_only:true});
    if(url.includes('/daily-watch'))return response({trading_date:'2026-09-11',symbols:[],slots_used:0,slot_limit:2});
    if(url.includes('/lottery-trackers'))return response(lottery);
    if(url.includes('/performance'))return response(performance);
    if(url.includes('/backtests'))return response([]);
    return new Response('not found',{status:404});
  });
  render(<App/>);
  await waitFor(()=>expect(screen.getByText('NO QUALIFIED PARLAYS RIGHT NOW')).toBeInTheDocument());
  const refresh=screen.getByRole('button',{name:'Refresh'});fireEvent.click(refresh);fireEvent.click(refresh);
  const automaticScan=interval.mock.calls.find(([,delay])=>delay===PARLAY_REFRESH_INTERVAL_MS)?.[0];
  await act(async()=>{if(typeof automaticScan==='function')automaticScan()});
  expect(parlayCalls).toBe(2);expect(refresh).toBeDisabled();expect(screen.getByText('Refreshing…')).toBeVisible();
  await act(async()=>rejectRefresh?.(new Error('scan failed')));
  await waitFor(()=>expect(screen.getByText('Stale data.')).toBeInTheDocument());
  expect(screen.getByText('NO QUALIFIED PARLAYS RIGHT NOW')).toBeInTheDocument();expect(refresh).toBeEnabled();
});

test('keeps prior order for same-status candidates with similar scores',()=>{
  const spy={symbol:'SPY',strategy_mode:'ONE_MIN_0DTE',signal_status:'WATCH',score:80,ranking_position:1} as ParlayCandidate;
  const qqq={symbol:'QQQ',strategy_mode:'ONE_MIN_0DTE',signal_status:'WATCH',score:79.5,ranking_position:2} as ParlayCandidate;
  const previous={...board,universe:['SPY','QQQ'],scanner_health:{candidate_count:2,unavailable_candidate_count:0,provider_status:'healthy'},candidates:[spy,qqq]};
  const next={...previous,candidates:[{...qqq,score:80.2,ranking_position:1},{...spy,ranking_position:2}]};
  expect(stabilizeCandidateOrder(next,previous).candidates.map(candidate=>candidate.symbol)).toEqual(['SPY','QQQ']);
});
