import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {ForwardPaperAccount} from './ForwardPaperAccount';
import type {ForwardAccount} from '../types';

afterEach(()=>{cleanup();vi.restoreAllMocks()});

function account(overrides:Partial<ForwardAccount>={}):ForwardAccount{
  return {status:'ACTIVE',paper_only:true,account_key:'forward-cash-v1',activated_at:'2026-10-12T13:30:00Z',as_of:'2026-10-12T14:00:00Z',processed_at:'2026-10-12T14:00:00Z',processing_stale:false,
    policy:{starting_cash_cents:200000,max_positions:3,max_entry_cents:10000,slippage_premium_cents:1,opening_commission_cents:100,closing_commission_cents:0,fee_allowance_per_side_cents:50,quote_age_seconds:60,entry_deadline_seconds:120,exit_deadline_seconds:180},
    settled_cents:195200,unsettled_cents:7400,available_cents:195200,reserved_exit_fees_cents:0,realized_cents:2600,charged_fees_cents:200,open_entry_fees_cents:0,known_liquidation_cents:0,unpriced_positions:0,unpriced_debit_cents:0,equity_cents:202600,
    daily:[{date:'2026-10-12',cash_cents:202600,realized_cents:2600}],positions:[],
    events:[{id:1,kind:'FUNDING',at:'2026-10-12T13:30:00Z',settled_cents:200000,unsettled_cents:0,fee_cents:0,realized_cents:0,detail:{reason:'New simulated capital'}}],
    pagination:{page:1,pages:1,total:1,page_size:20},...overrides};
}

test('separates simulated net profit, buying power, unsettled proceeds and costs',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>account()} as Response);
  render(<ForwardPaperAccount/>);
  await screen.findByText('$2,000.00 starting cash');
  const net=screen.getByText('Net realized P/L').parentElement!;
  expect(within(net).getByText('$26.00')).toBeInTheDocument();
  expect(within(screen.getByText('Unsettled proceeds').parentElement!).getByText('$74.00')).toBeInTheDocument();
  expect(screen.getByRole('img',{name:'Forward account cash held, not profit'})).toBeInTheDocument();
  expect(screen.getByRole('img',{name:'Forward account net realized P/L'})).toBeInTheDocument();
  expect(screen.getByText(/Lotto and manual trades stay separate/)).toBeInTheDocument();
  expect(screen.getByText(/not a broker invoice/)).toBeInTheDocument();
  expect(screen.getByText(/not proof of executable returns/)).toBeInTheDocument();
});

test('unknown exposure never renders as complete equity or fabricated zero loss',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>account({equity_cents:null,unpriced_positions:1,unpriced_debit_cents:4750,positions:[{id:2,status:'UNPRICED',option_symbol:'SPY261012C00100000',entry_debit_cents:4750,reason:'No verified exit'}]})} as Response);
  render(<ForwardPaperAccount/>);
  await screen.findByText('Incomplete');
  expect(screen.getByText(/Their value is unknown—not zero/)).toBeInTheDocument();
  expect(screen.getByText('No verified exit')).toBeInTheDocument();
  expect(within(screen.getByText('Estimated liquidation equity').parentElement!).queryByText('$2,026.00')).not.toBeInTheDocument();
});

test('ledger pagination requests another page and does not reset account',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>({ok:true,json:async()=>account({pagination:{page:String(url).endsWith('=2')?2:1,pages:2,total:21,page_size:20}})}) as Response);
  render(<ForwardPaperAccount/>);
  await screen.findByText('Page 1 of 2 · 21 events');
  fireEvent.click(screen.getByRole('button',{name:'Next cash events'}));
  await screen.findByText('Page 2 of 2 · 21 events');
  expect(fetch).toHaveBeenCalledWith('/api/forward-paper-account?page=2');
  expect(screen.getByRole('button',{name:'Next cash events'})).toBeDisabled();
  expect(fetch.mock.calls.every(call=>call.length===1)).toBe(true);
});

test('unactivated account is honest and does not manufacture a balance',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>({status:'NOT_STARTED',paper_only:true})} as Response);
  render(<ForwardPaperAccount/>);
  await screen.findByText(/Not started/);
  expect(screen.queryByText('Net realized P/L')).not.toBeInTheDocument();
});

test('failed requests display unavailability instead of zero results',async()=>{
  vi.spyOn(globalThis,'fetch').mockRejectedValue(new Error('offline'));
  render(<ForwardPaperAccount/>);
  await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('Account update unavailable'));
  expect(screen.queryByText('$0.00')).not.toBeInTheDocument();
});
