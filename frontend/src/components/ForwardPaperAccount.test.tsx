import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {ForwardPaperAccount} from './ForwardPaperAccount';
import {AccountEquityChart} from './AccountEquityChart';
import {equitySegments} from '../lib/accountEquity';
import {AccountCapacity} from './AccountCapacity';
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
  expect(screen.queryByText('Net realized P/L')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Account details'}));
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
  await screen.findByText(/held position\(s\) have unknown value/);
  fireEvent.click(screen.getByRole('button',{name:'Account details'}));
  await screen.findByText('Incomplete');
  expect(screen.getByText(/Their value is unknown—not zero/)).toBeInTheDocument();
  expect(screen.getByText('No verified exit')).toBeInTheDocument();
  expect(within(screen.getByText('Estimated liquidation equity').parentElement!).queryByText('$2,026.00')).not.toBeInTheDocument();
});

test('ledger pagination requests another page and does not reset account',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>({ok:true,json:async()=>account({pagination:{page:String(url).endsWith('=2')?2:1,pages:2,total:21,page_size:20}})}) as Response);
  render(<ForwardPaperAccount/>);
  await screen.findByRole('button',{name:'Account details'});
  fireEvent.click(screen.getByRole('button',{name:'Account details'}));
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

test('scheduled trial exposes preserved legacy account without creating a pretend balance',async()=>{
  const choices=[{key:'tasty-session-v2-20261019',label:'Tastytrade · corrected trial',archived:false},
    {key:'forward-cash-v1',label:'Legacy research · forward-cash-v1',archived:true}];
  const pending={status:'SCHEDULED',paper_only:true,accounts:choices,scheduled_start:'2026-10-19T13:30:00Z',starting_cash_cents:200000};
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>({ok:true,json:async()=>String(url).includes('forward-cash-v1')
    ? account({status:'ARCHIVED',accounts:choices,equity_cents:null,unpriced_positions:1,unpriced_debit_cents:4750,
      positions:[{id:2,status:'UNPRICED',option_symbol:'SPY261012C00100000',entry_debit_cents:4750,reason:'Original missing exit'}]})
    : pending}) as Response);
  render(<ForwardPaperAccount/>);
  await screen.findByText(/Scheduled for Oct 19, 2026/);
  expect(screen.queryByText('Net realized P/L')).not.toBeInTheDocument();
  expect(screen.queryByText('+$0.00 (0.00%) since funding')).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox',{name:'Paper trial'}),{target:{value:'forward-cash-v1'}});
  await screen.findByText(/Legacy research — read-only/);
  expect(screen.getByText(/Archived account · last processed/)).toBeInTheDocument();
  expect(screen.getByText(/missing history will not be backfilled/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Account details'}));
  expect(screen.getByText('Original missing exit')).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith('/api/forward-paper-account?page=1&account_key=forward-cash-v1');
  fireEvent.change(screen.getByRole('combobox',{name:'Paper trial'}),{target:{value:choices[0].key}});
  await screen.findByText(/Scheduled for Oct 19, 2026/);
  expect(screen.queryByText('Original missing exit')).not.toBeInTheDocument();
  expect(fetch.mock.calls.every(call=>call.length===1)).toBe(true);
});

test('changing trial resets pagination and never displays the previous account as current',async()=>{
  const choices=[{key:'tasty-session-v2-20261019',label:'Corrected trial',archived:false},
    {key:'forward-cash-v1',label:'Legacy research',archived:true}];
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>({ok:true,json:async()=>{
    const params=new URL(String(url),'http://test').searchParams;
    return account({status:params.get('account_key')==='forward-cash-v1'?'ARCHIVED':'ACTIVE',accounts:choices,
      pagination:{page:Number(params.get('page')),pages:2,total:21,page_size:20}});
  }}) as Response);
  render(<ForwardPaperAccount/>);
  await screen.findByRole('button',{name:'Account details'});
  fireEvent.click(screen.getByRole('button',{name:'Account details'}));
  await screen.findByText('Page 1 of 2 · 21 events');
  fireEvent.click(screen.getByRole('button',{name:'Next cash events'}));
  await screen.findByText('Page 2 of 2 · 21 events');
  fireEvent.change(screen.getByRole('combobox',{name:'Paper trial'}),{target:{value:'forward-cash-v1'}});
  await screen.findByRole('button',{name:'Account details'});
  fireEvent.click(screen.getByRole('button',{name:'Account details'}));
  await screen.findByText('Page 1 of 2 · 21 events');
  expect(fetch).toHaveBeenCalledWith('/api/forward-paper-account?page=1&account_key=forward-cash-v1');
  expect(screen.queryByText(/Current estimate ·/)).not.toBeInTheDocument();
});

const equityPoints=[
  {at:'2026-10-12T13:30:00Z',date:'2026-10-12',equity_cents:200000,return_percent:0,unpriced_positions:0},
  {at:'2026-10-12T13:31:00Z',date:'2026-10-12',equity_cents:null,return_percent:null,unpriced_positions:1},
  {at:'2026-10-12T13:32:00Z',date:'2026-10-12',equity_cents:202600,return_percent:1.3,unpriced_positions:0},
];

test('equity graph uses account return, supports dollar/range controls and exposes unknown gaps',()=>{
  render(<AccountEquityChart account={account({equity_history:{baseline_cents:200000,started_at:equityPoints[0].at,daily:equityPoints,intraday:equityPoints,basis:'Observed'}})}/>);
  expect(screen.getByText('+$26.00 (+1.30%) since funding')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Return %'})).toHaveAttribute('aria-pressed','true');
  expect(screen.getByRole('img',{name:'Paper account percentage return since funding'})).toBeInTheDocument();
  expect(screen.getAllByTestId('equity-segment')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button',{name:'Value $'}));
  expect(screen.getByRole('img',{name:'Paper account liquidation value in dollars'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'1D'}));
  expect(screen.getByRole('button',{name:'1D'})).toHaveAttribute('aria-pressed','true');
  fireEvent.change(screen.getByRole('slider',{name:'Inspect saved account value'}),{target:{value:'1'}});
  expect(screen.getByText('Value incomplete')).toBeInTheDocument();
  expect(screen.getByText('Return unavailable while positions are unpriced')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Show current estimate'}));
  expect(screen.getByText('+$26.00 (+1.30%) since funding')).toBeInTheDocument();
  for(const range of ['1W','1M','ALL']){
    fireEvent.click(screen.getByRole('button',{name:range}));
    expect(screen.getByText('+$26.00 (+1.30%) since funding')).toBeInTheDocument();
  }
});

test('equity graph never reconstructs history from old realized P/L or cash series',()=>{
  render(<AccountEquityChart account={account()}/>);
  expect(screen.getByText(/No saved equity observations/)).toBeInTheDocument();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

test('intraday quote-collection gaps break the line even if both endpoints are priced',()=>{
  const later={...equityPoints[2],at:'2026-10-12T14:00:00Z'};
  expect(equitySegments([equityPoints[0],later],true)).toHaveLength(2);
  expect(equitySegments(equityPoints,true)).toHaveLength(2);
  expect(equitySegments([{...equityPoints[0],equity_cents:0,return_percent:-100}],true)).toHaveLength(1);
});

test('full account explicitly explains unresolved slots and links to uncapped research',()=>{
  render(<AccountCapacity account={account({positions:[1,2,3].map(id=>({id,status:'UNPRICED',option_symbol:`TEST${id}`}))})}/>);
  expect(screen.getByText(/New entries blocked: account full · 3\/3 occupied/)).toBeVisible();
  expect(screen.getByText('0 open · 3 unresolved exits · 0 slots free.')).toBeVisible();
  expect(screen.getByRole('link',{name:'Open Research'})).toHaveAttribute('href','#backtest-lab');
  expect(screen.getByText(/cannot release them or calculate their profit/)).toBeVisible();
});

test('ten-slot display counts held exposure only, not pending entries or unsettled proceeds',()=>{
  const a=account();
  render(<AccountCapacity account={account({policy:{...a.policy,max_positions:10},unpriced_positions:2,
    positions:['OPEN','OPEN','PENDING_ENTRY','UNSETTLED'].map((status,id)=>({id,status,option_symbol:`TEST${id}`}))})}/>);
  expect(screen.getByText('2 open · 0 unresolved exits · 8 slots free.')).toBeVisible();
  expect(screen.queryByText(/New entries blocked/)).not.toBeInTheDocument();
  expect(screen.getByText(/Free slots alone do not guarantee a fill/)).toBeVisible();
});

test('archived account never suggests free slots allow new fills',()=>{
  render(<AccountCapacity account={account({status:'ARCHIVED'})}/>);
  expect(screen.getByText(/Archived account capacity/)).toBeVisible();
  expect(screen.getByText(/This preserved account accepts no new entries/)).toBeVisible();
});

test('new ten-position account requires explicit activation and never shows pretend funding',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>({status:'NOT_STARTED',paper_only:true,
    activation_required:true,starting_cash_cents:200000})} as Response);
  render(<ForwardPaperAccount/>);
  expect(await screen.findByText(/requires explicit after-hours activation/)).toBeVisible();
  expect(screen.queryByText('$2,000.00 starting cash')).not.toBeInTheDocument();
});
