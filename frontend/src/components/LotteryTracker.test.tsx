import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type { LotteryTrackerDetail, LotteryTrackerList, LotteryTrackerSummary } from '../types';
import { LotteryLab } from './LotteryTracker';

afterEach(()=>{cleanup();vi.restoreAllMocks()});

const tracker:LotteryTrackerSummary={
  id:'tracker-1',trading_date:'2026-09-02',symbol:'SPY',option_symbol:'SPY260902C00102000',
  expiration:'2026-09-02',right:'call',strike:102,status:'ACTIVE',first_seen_at:'2026-09-02T14:05:00Z',
  last_qualified_at:'2026-09-02T14:05:00Z',last_quote_at:'2026-09-02T14:06:00Z',closed_at:null,
  entry_ask:.20,entry_bid:.18,entry_cost:20,entry_underlying_price:101,setup_score:82,
  latest_bid:.45,latest_ask:.48,latest_sellable_value:45,latest_multiple:2.25,latest_return_percent:125,
  peak_bid:.45,peak_sellable_value:45,peak_multiple:2.25,peak_return_percent:125,
  peak_bid_at:'2026-09-02T14:06:00Z',hit_2x_at:'2026-09-02T14:06:00Z',hit_5x_at:null,hit_10x_at:null,
  point_count:2,currently_qualified:false,provider:'tradier',data_mode:'live',verification_status:'verified',
  verification_reason:'Verified contract',actionable:true,
};

const list:LotteryTrackerList={trading_date:'2026-09-02',trackers:[tracker],entry_basis:'First qualifying ask',performance_basis:'Subsequent sellable bid',paper_only:true};
const detail:LotteryTrackerDetail={tracker,entry_basis:list.entry_basis,performance_basis:list.performance_basis,paper_only:true,points:[
  {observed_at:'2026-09-02T14:05:00Z',quote_timestamp:'2026-09-02T14:05:00Z',bid_timestamp:'2026-09-02T14:05:00Z',ask_timestamp:'2026-09-02T14:05:00Z',bid:.18,ask:.20,midpoint:.19,last:.19,bid_value:18,ask_value:20,underlying_price:101,spread_percent:10,is_qualified:true,setup_score:82},
  {observed_at:'2026-09-02T14:06:00Z',quote_timestamp:'2026-09-02T14:06:00Z',bid_timestamp:'2026-09-02T14:06:00Z',ask_timestamp:'2026-09-02T14:06:00Z',bid:.45,ask:.48,midpoint:.465,last:.46,bid_value:45,ask_value:48,underlying_price:101.5,spread_percent:6.5,is_qualified:false,setup_score:null},
]};

test('opens a simple scan-by-scan option performance line chart',async()=>{
  vi.spyOn(globalThis,'fetch').mockImplementation(async(input)=>{
    const body=String(input).endsWith('/lottery-trackers')?list:detail;
    return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
  });
  render(<LotteryLab/>);
  const button=await screen.findByRole('button',{name:'View performance'});
  fireEvent.click(button);
  await waitFor(()=>expect(screen.getByText('Sellable value by scan')).toBeInTheDocument());
  expect(screen.getByLabelText('SPY call 102 sellable option value by scan')).toBeInTheDocument();
  expect(screen.getAllByText('2.25×').length).toBeGreaterThan(0);
  expect(screen.getAllByText('$45.00')).toHaveLength(2);
  expect(screen.getByText(/does not assume a fill at the midpoint/)).toBeInTheDocument();
});

test('shows a clear empty state when no lottery play was tracked',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({...list,trackers:[]}),{status:200,headers:{'Content-Type':'application/json'}}));
  render(<LotteryLab/>);
  expect(await screen.findByText('No active lottery candidate')).toBeInTheDocument();
  expect(screen.getByText(/most recent tracked session remains below/i)).toBeInTheDocument();
});
