import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { App } from './main';

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

afterEach(()=>vi.restoreAllMocks());
test('shows mock warning, symbols, lottery risk, journal and analytics', async()=>{
  const level={previous_day_high:552,previous_day_low:545,opening_range_high:551,opening_range_low:548,session_high:552,session_low:547,vwap:550,equal_highs:[],equal_lows:[547.25,547.5]};
  const dashboard={provider_status:{provider:'mock',mode:'mock',status:'healthy',delay_seconds:0,latest_timestamp:'2026-07-18T10:00:00-04:00',message:'Deterministic mock data; not live market data.'},quotes:['SPY','QQQ','IWM'].map((symbol,index)=>({symbol,price:550-index*20,timestamp:''})),market_session:'regular',volatility_proxy:14.2,levels:{SPY:level,QQQ:{...level,equal_highs:[486.25]},IWM:{...level,equal_lows:[]}},directional_bias:{SPY:'bullish',QQQ:'bullish',IWM:'bullish'},news_warning:'Calendar unavailable.',normal_setups:[],lottery_setups:[{symbol:'SPY',right:'call',strike:553,bid:.12,ask:.15,midpoint:.14,total_debit:15,spread_percent:22,delta:.2,gamma:.04,underlying_trigger:552,underlying_invalidation:550,break_even:553.15,estimated_2x_underlying:553.3,estimated_5x_underlying:553.75,estimated_10x_underlying:554.5,setup_score:80,explanation:'Estimate only.',worthless_reasons:['Can expire worthless']}],no_trade:false,paper_account:{mode:'PAPER ONLY',equity:25000,kill_switch:false}};
  const parlay={provider_status:dashboard.provider_status,universe:['SPY'],paper_only:true,candidates:[{ranking_position:1,symbol:'SPY',rank:'PLAY',direction:'call',signal_status:'BUY',score:90,score_label:'PLAY',underlying_price:550,contract:null,contract_cost:null,midpoint:null,spread_percent:null,entry_low:.4,entry_high:.48,no_chase_price:.57,underlying_trigger:551,underlying_invalidation:549,first_underlying_target:552,stretch_underlying_target:554,first_option_target:.96,stretch_option_target:1.92,reasons:['Price reclaimed VWAP'],rejection_reasons:[],unavailable_reason:null,primary_action:'BUY BELOW $0.48',generated_at:'',data_freshness:'mock_current'}]};
  vi.spyOn(globalThis,'fetch').mockImplementation(async(input)=>{const url=String(input);const body=url.includes('parlays')?parlay:url.includes('dashboard')?dashboard:url.includes('journal')?[{id:1,symbol:'SPY',signal_type:'lottery',status:'not_taken',generated_at:'',payload:{}}]:{minimum_sample_size:30,sample_size:6,statistically_promising:false,win_rate:50,profit_factor:1.2,average_winner:20,average_loser:-15,expectancy:2,message:'Seeded results.'};return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}})});
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
