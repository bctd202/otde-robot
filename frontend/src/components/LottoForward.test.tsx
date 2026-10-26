import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {LottoForward} from './LottoForward';

afterEach(()=>{cleanup();vi.restoreAllMocks()});
const accounts=['both-fixed5','both-trail40','call-fixed5','call-trail40','put-fixed5','put-trail40'].map(key=>({key,label:key,scope:key.startsWith('both')?'combined':'directional'}));
const scheduled={status:'SCHEDULED',account_key:accounts[0].key,accounts,scheduled_start:'2026-10-26T13:30:00Z'};
const active={status:'ACTIVE',accounts,account_key:accounts[0].key,policy:{starting_cash_cents:50000},
  as_of:'2026-10-19T15:00:00Z',processed_at:'2026-10-19T15:00:00Z',activated_at:'2026-10-19T13:30:00Z',
  equity_cents:53000,settled_cents:48000,unsettled_cents:5000,realized_cents:3000,unpriced_positions:0,
  equity_history:{baseline_cents:50000,started_at:'2026-10-19T13:30:00Z',daily:[],intraday:[],basis:'Test'},
  direction_breakdown:[{right:'call',entered:2,closed:1,open:0,unpriced:1,pending:0,skipped:2,realized_cents:4500},
    {right:'put',entered:1,closed:1,open:0,unpriced:0,pending:0,skipped:3,realized_cents:-1500}],
  trades:[{id:1,tracker_id:'tracker1',status:'UNSETTLED',option_symbol:'SPY test',entry_debit_cents:2000,net_proceeds_cents:5000}],pagination:{page:1,pages:2,total:13}};

test('defaults to shared fixed5 and scheduled accounts cannot look funded',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response(JSON.stringify(scheduled)));
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByText(/Scheduled ·/);
  expect(screen.getByRole('button',{name:/^5× Exit/})).toHaveAttribute('aria-pressed','true');
  expect(screen.getAllByRole('option')).toHaveLength(5);
  expect(screen.getByRole('group',{name:'Shared calls and puts exit rule'})).toBeInTheDocument();
  expect(screen.queryByRole('region',{name:'Account value and percentage return'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Other experiment versions'));
  fireEvent.change(screen.getByRole('combobox',{name:'Experiment version'}),{target:{value:'put-fixed5'}});
  await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/lotto-paper-trials?page=1&account_key=put-fixed5&view=ENTERED'));
  expect(screen.getByText(/Never add these balances together/)).toBeInTheDocument();
});

test('switches exit rules and original comparisons without combining balances',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async(input)=>{
    const key=new URL(String(input),'http://localhost').searchParams.get('account_key')??accounts[0].key;
    return new Response(JSON.stringify({...active,account_key:key}));
  });
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByRole('region',{name:'Calls versus puts breakdown'});
  expect(screen.getByText('Closed-trade P/L +$45.00')).toBeInTheDocument();
  expect(screen.getByText('Closed-trade P/L −$15.00')).toBeInTheDocument();
  expect(screen.getByText(/2 entered · 1 closed · 0 open · 1 unknown/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Trades'}));
  fireEvent.click(screen.getByRole('button',{name:'Next trades'}));
  await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/lotto-paper-trials?page=2&view=ENTERED'));
  fireEvent.click(screen.getByRole('button',{name:/^Trail after 2×/}));
  await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/lotto-paper-trials?page=1&account_key=both-trail40&view=ENTERED'));
  await screen.findByRole('button',{name:/^Trail after 2×/});
  fireEvent.click(screen.getByText('Other experiment versions'));
  fireEvent.change(screen.getByRole('combobox',{name:'Experiment version'}),{target:{value:'put-fixed5'}});
  await screen.findByText(/Original directional comparison—not a shared/);
  expect(screen.getByRole('combobox',{name:'Experiment version'})).toHaveValue('put-fixed5');
});

test('forward account defaults to balance, paginates trades and opens evidence',async()=>{
  const inspect=vi.fn();
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async(input)=>new Response(JSON.stringify({...active,
    pagination:{...active.pagination,page:String(input).includes('page=2')?2:1}})));
  render(<LottoForward onInspect={inspect}/>);
  await screen.findByRole('region',{name:'Account value and percentage return'});
  expect(screen.queryByText('SPY test')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Trades'}));
  expect(screen.getByText('gain $30.00 · +150.0%')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Inspect quote path'}));
  expect(inspect).toHaveBeenCalledWith('tracker1');
  fireEvent.click(screen.getByRole('button',{name:'Next trades'}));
  await screen.findByText('Page 2 of 2');
  expect(fetch).toHaveBeenCalledWith('/api/lotto-paper-trials?page=2&view=ENTERED');
});

test('quote gaps remain visible and invalid responses show unavailable',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({...active,equity_cents:null,unpriced_positions:1})));
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByText(/unknown liquidation value/);
  expect(screen.queryByText('+$30.00 (+6.00%) since funding')).not.toBeInTheDocument();
  cleanup();
  vi.mocked(fetch).mockResolvedValue(new Response('{}'));
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByRole('alert');
  expect(screen.queryByText('$0.00')).not.toBeInTheDocument();
});

test('new contract ceiling is separate from daily spending and legacy accounts remain accessible',async()=>{
  const nextAccounts=[...accounts.map(a=>({...a,generation:a.scope==='combined'?'single':'directional'})),
    ...['fixed5','trail40'].map(rule=>({key:`multi-${rule}`,label:`Multi ${rule}`,scope:'combined',generation:'multi'}))];
  vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({...active,accounts:nextAccounts,account_key:'multi-fixed5'})));
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByRole('region',{name:'Calls versus puts breakdown'});
  expect(screen.getByText(/Maximum \$100 premium per standard contract/)).toHaveTextContent('No daily spending cap');
  expect(screen.getAllByText(/5 slots/)).toHaveLength(2);
  fireEvent.click(screen.getByText('Other experiment versions'));
  expect(screen.getAllByRole('option')).toHaveLength(7);
});

test('trade filters request separate server pages and do not label skips as losses',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async input=>new Response(JSON.stringify({...active,
    trades:String(input).includes('view=SKIPPED')?[]:active.trades,pagination:{page:1,pages:1,total:0}})));
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByRole('region',{name:'Calls versus puts breakdown'});
  fireEvent.click(screen.getByRole('button',{name:'Trades'}));
  expect(screen.getByRole('button',{name:'Entered trades'})).toHaveAttribute('aria-pressed','true');
  fireEvent.click(screen.getByRole('button',{name:'Skipped opportunities'}));
  await screen.findByText('No skipped opportunities in this account.');
  expect(fetch).toHaveBeenCalledWith('/api/lotto-paper-trials?page=1&view=SKIPPED');
  expect(screen.queryByText('gain $30.00 · +150.0%')).not.toBeInTheDocument();
});

test('planned multi-position accounts cannot appear active or funded',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({...scheduled,
    status:'NOT_STARTED',scheduled_start:null,activation_required:true})));
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByText(/Not activated — requires explicit approval/);
  expect(screen.queryByRole('region',{name:'Account value and percentage return'})).not.toBeInTheDocument();
});
