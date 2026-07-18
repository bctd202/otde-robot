import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { App } from './main';

afterEach(()=>vi.restoreAllMocks());
test('shows mock warning, symbols, lottery risk, journal and analytics', async()=>{
  const dashboard={provider_status:{provider:'mock',mode:'mock',status:'healthy',delay_seconds:0,latest_timestamp:'2026-07-18T10:00:00-04:00',message:'Deterministic mock data; not live market data.'},quotes:['SPY','QQQ','IWM'].map((symbol,index)=>({symbol,price:550-index*20,timestamp:''})),market_session:'regular',volatility_proxy:14.2,levels:{SPY:{vwap:550}},directional_bias:{SPY:'bullish',QQQ:'bullish',IWM:'bullish'},news_warning:'Calendar unavailable.',normal_setups:[],lottery_setups:[{symbol:'SPY',right:'call',strike:553,bid:.12,ask:.15,midpoint:.14,total_debit:15,spread_percent:22,delta:.2,gamma:.04,underlying_trigger:552,underlying_invalidation:550,break_even:553.15,estimated_2x_underlying:553.3,estimated_5x_underlying:553.75,estimated_10x_underlying:554.5,setup_score:80,explanation:'Estimate only.',worthless_reasons:['Can expire worthless']}],no_trade:false,paper_account:{mode:'PAPER ONLY',equity:25000,kill_switch:false}};
  vi.spyOn(globalThis,'fetch').mockImplementation(async(input)=>new Response(JSON.stringify(String(input).includes('dashboard')?dashboard:String(input).includes('journal')?[{id:1,symbol:'SPY',signal_type:'lottery',status:'not_taken',generated_at:'',payload:{}}]:{minimum_sample_size:30,sample_size:6,statistically_promising:false,win_rate:50,profit_factor:1.2,average_winner:20,average_loser:-15,expectancy:2,message:'Seeded results.'}),{status:200,headers:{'Content-Type':'application/json'}}));
  render(<App/>);
  await waitFor(()=>expect(screen.getByText('MOCK DATA — NOT LIVE')).toBeInTheDocument());
  expect(screen.getByText('SPY')).toBeInTheDocument();
  expect(screen.getByText(/Most lottery contracts/)).toBeInTheDocument();
  expect(screen.getByText(/Signal Journal/)).toBeInTheDocument();
});
