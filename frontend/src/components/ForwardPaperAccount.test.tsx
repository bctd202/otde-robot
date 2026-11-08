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

test('collection boundary labels the continuous balance without rewriting unknown trades',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>account({execution_boundaries:[{
    at:'2026-10-30T13:30:00Z',execution_version:'decision-clock-v2',reason:'Prospective collection repair'}]})} as Response);
  render(<ForwardPaperAccount/>);
  expect(await screen.findByText(/The account balance spans both collection versions/)).toBeVisible();
});

test.each(['legacy','canonical'])('frozen %s cost units display as cents per share',async(kind)=>{
  const policy={...account().policy};
  if(kind==='canonical'){delete policy.slippage_premium_cents;policy.slippage_cents_per_share=1}
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>account({policy})} as Response);
  render(<ForwardPaperAccount/>);
  fireEvent.click(await screen.findByRole('button',{name:'Account details'}));
  fireEvent.click(screen.getByText('Frozen assumptions & limitations'));
  expect(screen.getByText(/Ask \+ \$0.01 premium per share at entry/)).toBeVisible();
  expect(screen.queryByText(/Ask \+ \$1.00 premium/)).not.toBeInTheDocument();
});

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

test('ended trades move outside live capacity but keep the full account total unknown',async()=>{
  const ended={id:86,status:'ENDED_UNRESOLVED',option_symbol:'SPY261029C00772000',
    entry_debit_cents:7750,expiration:'2026-10-29',entry_dte:0,lifecycle_label:'Expired · exit price missing',capacity_released:true};
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>account({equity_cents:null,
    unpriced_positions:1,unpriced_debit_cents:7750,expired_unresolved_count:1,expired_unresolved_debit_cents:7750,
    unresolved_expirations:[ended],positions:[],trades:[ended],
    lifecycle_policy:{version:'session-end-state-v1',ended_contracts_use_live_slots:false,missing_proceeds_are_zero:false}})} as Response);
  render(<ForwardPaperAccount/>);
  expect(await screen.findByText('Total pending historical exit evidence')).toBeVisible();
  expect(screen.getByText('0 open · 0 unresolved exits · 3 slots free.')).toBeVisible();
  expect(screen.getByText('1 expired/session-ended trade(s) · $77.50 original cost')).toBeVisible();
  expect(screen.getByText(/slots are released—not their spent entry cash/)).toBeVisible();
  expect(screen.getByText(/Cash alone is not the total account value or profit/)).toBeVisible();
  expect(screen.queryByText(/held position\(s\) have unknown value/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Trades'}));
  expect(screen.getByText('Expired · exit price missing · Paper')).toBeVisible();
});

test('an old unpriced observation never inherits the current expired-trade explanation',()=>{
  render(<AccountEquityChart account={account({equity_cents:null,expired_unresolved_count:1,
    equity_history:{baseline_cents:200000,started_at:equityPoints[0].at,daily:equityPoints,intraday:equityPoints,basis:'Observed'}})}/>);
  expect(screen.getByText('Total pending historical exit evidence')).toBeVisible();
  fireEvent.change(screen.getByRole('slider',{name:'Inspect saved account value'}),{target:{value:'1'}});
  expect(screen.getByText('Value incomplete')).toBeVisible();
  expect(screen.queryByText('Missing exit proceeds—not a live-price loading problem. Complete account return remains unknown.')).not.toBeInTheDocument();
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

const writeoffs:NonNullable<ForwardAccount['write_off_adjustments']>={version:'manual-zero-write-off-v1',
  count:3,loss_cents:17950,first_recorded_at:'2026-10-12T13:32:00Z',last_recorded_at:'2026-10-12T13:32:00Z',
  verified_exit_evidence:false,historical_snapshots_rewritten:false,adjustments:[]};

test('adjusted totals keep completed-trade results separate and label graph assumptions',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>account({write_off_adjustments:writeoffs,
    realized_cents:5050,confirmed_realized_cents:23000})} as Response);
  render(<ForwardPaperAccount/>);
  const warning=await screen.findByLabelText('Manual write-off adjustments');
  expect(warning).toHaveTextContent('3 manual write-off(s) · $179.50 modeled loss');
  expect(warning).toHaveTextContent('Completed simulated trades: $230.00 net P/L. Including manual write-offs: $50.50.');
  expect(warning).toHaveTextContent('cash was not debited again');
  expect(screen.getByText('WRITE-OFF ADJUSTED ACCOUNT VALUE · SIMULATED')).toBeVisible();
  expect(screen.getByText(/This is not a fully verified account return/)).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Account details'}));
  expect(screen.getByText('Realized P/L · write-off adjusted')).toBeVisible();
  expect(screen.getByRole('img',{name:'Forward account P/L including manual write-offs'})).toBeVisible();
});

test('historical gaps remain gaps and earlier observations are not relabeled as adjusted',()=>{
  const points=equityPoints.map((point,i)=>({...point,manual_write_off_count:i===2?3:0}));
  render(<AccountEquityChart account={account({write_off_adjustments:writeoffs,
    equity_history:{baseline_cents:200000,started_at:points[0].at,daily:points,intraday:points,basis:'Observed'}})}/>);
  expect(screen.getByRole('img',{name:'Write-off adjusted Paper account percentage return since funding'})).toBeVisible();
  expect(screen.getAllByTestId('equity-segment')).toHaveLength(2);
  fireEvent.change(screen.getByRole('slider',{name:'Inspect saved account value'}),{target:{value:'0'}});
  expect(screen.getByText('OPTION-DOLLAR ACCOUNT VALUE · SIMULATED')).toBeVisible();
  expect(screen.queryByText('WRITE-OFF ADJUSTED ACCOUNT VALUE · SIMULATED')).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('slider',{name:'Inspect saved account value'}),{target:{value:'1'}});
  expect(screen.getByText('Value incomplete')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Show current estimate'}));
  expect(screen.getByText('WRITE-OFF ADJUSTED ACCOUNT VALUE · SIMULATED')).toBeVisible();
});

const includedTrade={id:200,status:'CLOSED',option_symbol:'QQQ included trade',entry_debit_cents:2000,net_proceeds_cents:9400};
const archivedTrade={id:86,status:'WRITTEN_OFF',option_symbol:'SPY excluded data failure',entry_debit_cents:7750,net_proceeds_cents:null};
function researchAccount():ForwardAccount{
  const points=[{at:'2026-10-12T13:30:00Z',date:'2026-10-12',equity_cents:200000,return_percent:0,unpriced_positions:0},
    {at:'2026-10-12T14:00:00Z',date:'2026-10-12',equity_cents:207400,return_percent:3.7,unpriced_positions:0}];
  return account({account_key:'tasty-capacity-ten-v1',write_off_adjustments:writeoffs,
    equity_cents:189450,settled_cents:189450,unsettled_cents:0,available_cents:189450,
    realized_cents:-10550,confirmed_realized_cents:7400,open_trades:[],recent_trades:[includedTrade],trades:[includedTrade],
    data_exclusions:{version:'test-exclusions',state:'APPLIED_TO_RESEARCH_VIEW',excluded_count:3,excluded_debit_cents:17950,reason:'Missing exit data',positions:[]},
    research_view:{version:'test-exclusions',excluded_count:3,excluded_debit_cents:17950,equity_cents:207400,
      realized_cents:7400,basis:'ADJUSTED_RESEARCH_VALUE_NOT_CASH',cash_ledger_changed:false,capacity_replayed:false,
      included_manual_write_off_count:0,reason:'Missing exit data',
      equity_history:{baseline_cents:200000,started_at:points[0].at,daily:points,intraday:points,basis:'Derived comparison'}},
    execution_boundaries:[{at:'2026-10-12T13:30:00Z',execution_version:'test',reason:'Frozen history'}]});
}

test('simple overview has one research graph, open positions and recent trades without giant historical banners',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>researchAccount()} as Response);
  render(<ForwardPaperAccount/>);
  expect(await screen.findByRole('heading',{name:'Your results'})).toBeVisible();
  expect(screen.getByText('$2,074.00')).toBeVisible();
  expect(screen.getByText('+$74.00 (+3.70%) · included trades')).toBeVisible();
  expect(screen.getByRole('button',{name:'3 data exclusions'})).toBeVisible();
  expect(screen.getByLabelText('Open positions')).toHaveTextContent('No open positions.');
  expect(screen.getByLabelText('Recent trades')).toHaveTextContent('QQQ included trade');
  expect(screen.getByText('Actual buying power · not the adjusted research value')).toBeVisible();
  expect(screen.queryByLabelText('Manual write-off adjustments')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Paper account capacity')).not.toBeInTheDocument();
  expect(screen.queryByText(/The account balance spans both collection versions/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Account details'}));
  expect(screen.getByLabelText('Manual write-off adjustments')).toBeVisible();
  expect(screen.getByText(/The account balance spans both collection versions/)).toBeVisible();
  expect(screen.getByText('Realized P/L · write-off adjusted').parentElement).toHaveTextContent('-$105.50');
});

test('exclusion archive is a separate read-only request and does not leak excluded rows back into included results',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>({ok:true,json:async()=>({
    ...researchAccount(),trades:String(url).includes('trade_view=EXCLUDED')?[archivedTrade]:[includedTrade],
  })}) as Response);
  render(<ForwardPaperAccount/>);
  await screen.findByRole('button',{name:'3 data exclusions'});
  expect(screen.queryByText('SPY excluded data failure')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'3 data exclusions'}));
  const archive=await screen.findByLabelText('Data exclusions archive');
  expect(archive).toHaveTextContent('SPY excluded data failure');
  expect(archive).not.toHaveTextContent('QQQ included trade');
  expect(fetch).toHaveBeenCalledWith('/api/forward-paper-account?page=1&trade_view=EXCLUDED');
  fireEvent.click(screen.getByRole('button',{name:'Overview'}));
  await screen.findByLabelText('Recent trades');
  expect(screen.queryByText('SPY excluded data failure')).not.toBeInTheDocument();
  expect(fetch.mock.calls.every(call=>call.length===1)).toBe(true);
});

test('new missing included valuations stay incomplete even when the approved exclusions exist',()=>{
  const data=researchAccount();data.research_view!.equity_cents=null;
  render(<AccountEquityChart account={data}/>);
  expect(screen.getByText('Result incomplete')).toBeVisible();
  expect(screen.getByText('Included trades still have missing price evidence.')).toBeVisible();
  expect(screen.queryByText('$2,074.00')).not.toBeInTheDocument();
});
