import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { App, PARLAY_REFRESH_INTERVAL_MS, stabilizeCandidateOrder } from './main';
import type { ParlayCandidate, ParlayResponse } from './types';

vi.mock('lightweight-charts', () => ({
  CandlestickSeries: {},
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
  LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, SparseDotted: 4 },
  createSeriesMarkers: vi.fn(),
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn(), createPriceLine: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
  }),
}));

afterEach(()=>{cleanup();vi.restoreAllMocks()});
test('shows mock warning, symbols, lottery risk, journal and analytics', async()=>{
  const level={previous_day_high:552,previous_day_low:545,opening_range_high:551,opening_range_low:548,session_high:552,session_low:547,vwap:550,equal_highs:[],equal_lows:[547.25,547.5]};
  const dashboard={provider_status:{provider:'mock',mode:'mock',status:'healthy',delay_seconds:0,latest_timestamp:'2026-07-18T10:00:00-04:00',message:'Deterministic mock data; not live market data.'},quotes:['SPY','QQQ','IWM'].map((symbol,index)=>({symbol,price:550-index*20,timestamp:''})),market_session:'regular',volatility_proxy:14.2,levels:{SPY:level,QQQ:{...level,equal_highs:[486.25]},IWM:{...level,equal_lows:[]}},directional_bias:{SPY:'bullish',QQQ:'bullish',IWM:'bullish'},news_warning:'Calendar unavailable.',normal_setups:[],lottery_setups:[{symbol:'SPY',right:'call',strike:553,bid:.12,ask:.15,midpoint:.14,total_debit:15,spread_percent:22,delta:.2,gamma:.04,underlying_trigger:552,underlying_invalidation:550,break_even:553.15,estimated_2x_underlying:553.3,estimated_5x_underlying:553.75,estimated_10x_underlying:554.5,setup_score:80,explanation:'Estimate only.',worthless_reasons:['Can expire worthless']}],no_trade:false,paper_account:{mode:'PAPER ONLY',equity:25000,kill_switch:false}};
  const parlay={provider_status:dashboard.provider_status,universe:['SPY'],paper_only:true,candidates:[{ranking_position:1,symbol:'SPY',rank:'PLAY',direction:'call',signal_status:'BUY',score:90,score_label:'PLAY',underlying_price:550,contract:null,contract_cost:null,midpoint:null,spread_percent:null,entry_low:.4,entry_high:.48,no_chase_price:.57,underlying_trigger:551,underlying_invalidation:549,first_underlying_target:552,stretch_underlying_target:554,first_option_target:.96,stretch_option_target:1.92,reasons:['Price reclaimed VWAP'],rejection_reasons:[],unavailable_reason:null,primary_action:'BUY BELOW $0.48',generated_at:'',data_freshness:'mock_current'}]};
  vi.spyOn(globalThis,'fetch').mockImplementation(async(input)=>{const url=String(input);const body=url.includes('paper-positions')?{positions:[],paper_only:true}:url.includes('parlays')?parlay:url.includes('dashboard')?dashboard:url.includes('journal')?[{id:1,symbol:'SPY',signal_type:'lottery',status:'not_taken',generated_at:'',payload:{}}]:{minimum_sample_size:30,sample_size:6,statistically_promising:false,win_rate:50,profit_factor:1.2,average_winner:20,average_loser:-15,expectancy:2,message:'Seeded results.'};return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}})});
  render(<App/>);
  await waitFor(()=>expect(screen.getByText('MOCK DATA — NOT LIVE')).toBeInTheDocument());
  expect(screen.getAllByText('SPY').length).toBeGreaterThan(0);
  expect(screen.getByText(/Most lottery contracts/)).toBeInTheDocument();
  expect(screen.getByText(/Signal Journal/)).toBeInTheDocument();
  expect(screen.getAllByText('None detected').length).toBeGreaterThan(0);
  const equalLowMatches = screen.getAllByText('547.25, 547.50');
  expect(equalLowMatches.length).toBeGreaterThan(0);
  expect(screen.getByLabelText('Liquidity context')).toBeInTheDocument();
  expect(screen.getByText('Recent Liquidity Events')).toBeInTheDocument();
  expect(screen.getByText(/Visual research score only/)).toBeInTheDocument();
});

const baseLevel={previous_day_high:552,previous_day_low:545,opening_range_high:551,opening_range_low:548,session_high:552,session_low:547,vwap:550,equal_highs:[],equal_lows:[]};

function renderDashboard(overrides:Record<string,unknown>) {
  const providerStatus={provider:'tradier',mode:'live',status:'healthy',delay_seconds:0,latest_timestamp:'2026-07-29T14:00:00-04:00',message:'Live Tradier market data; paper research only.'};
  const dashboard={provider_status:providerStatus,quotes:[{symbol:'SPY',price:550,timestamp:''}],market_session:'regular',volatility_proxy:null,levels:{SPY:baseLevel},directional_bias:{SPY:'bullish'},news_warning:'Calendar unavailable.',normal_setups:[],lottery_setups:[],no_trade:true,paper_account:{mode:'PAPER ONLY',equity:25000,kill_switch:false},...overrides};
  const parlay={provider_status:providerStatus,universe:['SPY'],paper_only:true,candidates:[]};
  vi.spyOn(globalThis,'fetch').mockImplementation(async(input)=>{
    const url=String(input);
    const body=url.includes('paper-positions')?{positions:[],paper_only:true}:url.includes('parlays')?parlay:url.includes('dashboard')?dashboard:url.includes('journal')?[]:{minimum_sample_size:30,sample_size:0,statistically_promising:false,win_rate:0,profit_factor:null,average_winner:0,average_loser:0,expectancy:0,message:'No samples.'};
    return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
  });
  return render(<App/>);
}

test('keeps the application visible when SPY liquidity levels are missing',async()=>{
  renderDashboard({levels:{QQQ:baseLevel},directional_bias:{}});
  await waitFor(()=>expect(screen.getByText('Chart unavailable')).toBeInTheDocument());
  expect(screen.getByText('Market Context')).toBeInTheDocument();
  expect(screen.getByText('Parlay')).toBeInTheDocument();
  expect(screen.getByText('LIVE MARKET DATA')).toBeInTheDocument();
  expect(screen.queryByText('MOCK DATA — NOT LIVE')).not.toBeInTheDocument();
});

test('shows chart and liquidity empty states when no levels are available',async()=>{
  renderDashboard({levels:{},directional_bias:{}});
  await waitFor(()=>expect(screen.getByText('Liquidity levels unavailable')).toBeInTheDocument());
  expect(screen.getByText('Chart unavailable')).toBeInTheDocument();
  expect(screen.getByText('The live provider did not return enough intraday data to build liquidity levels.')).toBeInTheDocument();
  expect(screen.getByText(/Parlay paper-only research/)).toBeInTheDocument();
});

test('uses the first quoted symbol with liquidity levels when SPY has none',async()=>{
  renderDashboard({quotes:[{symbol:'SPY',price:550,timestamp:''},{symbol:'QQQ',price:485,timestamp:''}],levels:{QQQ:{...baseLevel,vwap:485}},directional_bias:{QQQ:'bearish'}});
  await waitFor(()=>expect(screen.getByLabelText('QQQ one-minute candlestick chart')).toBeInTheDocument());
  expect(screen.getByLabelText('Liquidity context')).toHaveTextContent('bearish');
  expect(screen.queryByText('Chart unavailable')).not.toBeInTheDocument();
  expect(screen.getByText('Market Context')).toBeInTheDocument();
});

test('schedules automatic Parlay scans every 120 seconds',()=>{
  const interval=vi.spyOn(window,'setInterval');
  renderDashboard({});
  expect(PARLAY_REFRESH_INTERVAL_MS).toBe(120_000);
  expect(interval).toHaveBeenCalledWith(expect.any(Function),120_000);
});

test('manual refresh retains the board, prevents overlap, and marks a failed scan stale',async()=>{
  const interval=vi.spyOn(window,'setInterval');
  const providerStatus={provider:'tradier',mode:'live',status:'healthy',delay_seconds:0,latest_timestamp:'2026-07-29T14:00:00-04:00',message:'Live paper research data.'};
  const dashboard={provider_status:providerStatus,quotes:[],market_session:'regular',volatility_proxy:null,levels:{},directional_bias:{},news_warning:'',normal_setups:[],lottery_setups:[],no_trade:true,paper_account:{mode:'PAPER ONLY',equity:25000,kill_switch:false}};
  const board={provider_status:providerStatus,universe:['SPY'],scanner_health:{candidate_count:0,unavailable_candidate_count:0,provider_status:'healthy'},paper_only:true,candidates:[]};
  let parlayCalls=0;
  let rejectRefresh:((reason?:unknown)=>void)|undefined;
  vi.spyOn(globalThis,'fetch').mockImplementation(async(input)=>{
    const url=String(input);
    if(url.includes('parlays')){
      parlayCalls+=1;
      if(parlayCalls>1)return new Promise<Response>((_,reject)=>{rejectRefresh=reject});
      return new Response(JSON.stringify(board),{status:200,headers:{'Content-Type':'application/json'}});
    }
    const body=url.includes('paper-positions')?{positions:[],paper_only:true}:url.includes('dashboard')?dashboard:url.includes('journal')?[]:{minimum_sample_size:30,sample_size:0,statistically_promising:false,win_rate:0,profit_factor:null,average_winner:0,average_loser:0,expectancy:0,message:'No samples.'};
    return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
  });
  render(<App/>);
  await waitFor(()=>expect(screen.getByText('NO QUALIFIED PARLAYS RIGHT NOW')).toBeInTheDocument());
  const refresh=screen.getByRole('button',{name:'Refresh'});
  fireEvent.click(refresh);
  fireEvent.click(refresh);
  const automaticScan=interval.mock.calls.find(([,delay])=>delay===PARLAY_REFRESH_INTERVAL_MS)?.[0];
  await act(async()=>{if(typeof automaticScan==='function')automaticScan()});
  expect(parlayCalls).toBe(2);
  expect(refresh).toBeDisabled();
  expect(screen.getByText('NO QUALIFIED PARLAYS RIGHT NOW')).toBeInTheDocument();
  expect(screen.getByText('Refreshing…')).toBeVisible();
  await act(async()=>rejectRefresh?.(new Error('scan failed')));
  await waitFor(()=>expect(screen.getByText('Stale data.')).toBeInTheDocument());
  expect(screen.getByText('NO QUALIFIED PARLAYS RIGHT NOW')).toBeInTheDocument();
  expect(refresh).toBeEnabled();
});

test('keeps prior order for same-status candidates with similar scores',()=>{
  const spy={symbol:'SPY',signal_status:'WATCH',score:80,ranking_position:1} as ParlayCandidate;
  const qqq={symbol:'QQQ',signal_status:'WATCH',score:79.5,ranking_position:2} as ParlayCandidate;
  const previous={provider_status:{provider:'mock',mode:'mock',status:'healthy',delay_seconds:0,latest_timestamp:'',message:''},universe:['SPY','QQQ'],scanner_health:{candidate_count:2,unavailable_candidate_count:0,provider_status:'healthy'},paper_only:true,candidates:[spy,qqq]} satisfies ParlayResponse;
  const next={...previous,candidates:[{...qqq,score:80.2,ranking_position:1},{...spy,ranking_position:2}]};
  expect(stabilizeCandidateOrder(next,previous).candidates.map(candidate=>candidate.symbol)).toEqual(['SPY','QQQ']);
});

test.each([
  ['live', {provider:'tradier',mode:'live',status:'healthy',delay_seconds:0,message:'Verified live entitlement.'}, 'LIVE MARKET DATA', '0s'],
  ['delayed mode', {provider:'tradier',mode:'delayed',status:'healthy',delay_seconds:-1,message:'Delayed entitlement.'}, 'DELAYED MARKET DATA', 'Unknown'],
  ['positive delay', {provider:'tradier',mode:'unknown',status:'healthy',delay_seconds:900,message:'Delayed timestamp.'}, 'DELAYED MARKET DATA', '900s'],
  ['mock', {provider:'mock',mode:'mock',status:'healthy',delay_seconds:0,message:'Mock data.'}, 'MOCK DATA — NOT LIVE', '0s'],
  ['unknown', {provider:'tradier',mode:'unknown',status:'healthy',delay_seconds:-1,message:'Entitlement unknown.'}, 'UNKNOWN MARKET DATA', 'Unknown'],
])('renders honest %s provider banner and delay label',async(_,provider,label,delay)=>{
  renderDashboard({provider_status:{...provider,latest_timestamp:'2026-07-29T14:00:00-04:00'}});
  await waitFor(()=>expect(screen.getByText(label)).toBeInTheDocument());
  expect(screen.getByText('Delay').closest('.metric')).toHaveTextContent(delay);
});
