import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {LottoForward} from './LottoForward';

afterEach(()=>{cleanup();vi.restoreAllMocks()});
const accounts=['call-fixed5','call-trail40','put-fixed5','put-trail40'].map(key=>({key,label:key}));
const scheduled={status:'SCHEDULED',accounts,scheduled_start:'2026-10-19T13:30:00Z'};
const active={status:'ACTIVE',accounts,account_key:accounts[0].key,policy:{starting_cash_cents:50000},
  as_of:'2026-10-19T15:00:00Z',processed_at:'2026-10-19T15:00:00Z',activated_at:'2026-10-19T13:30:00Z',
  equity_cents:53000,settled_cents:48000,unsettled_cents:5000,realized_cents:3000,unpriced_positions:0,
  equity_history:{baseline_cents:50000,started_at:'2026-10-19T13:30:00Z',daily:[],intraday:[],basis:'Test'},
  trades:[{id:1,tracker_id:'tracker1',status:'UNSETTLED',option_symbol:'SPY test',entry_debit_cents:2000,net_proceeds_cents:5000}],pagination:{page:1,pages:2,total:13}};

test('scheduled accounts cannot look funded and choosing PUT stays separate',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response(JSON.stringify(scheduled)));
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByText(/Scheduled ·/);
  expect(screen.queryByRole('region',{name:'Account value and percentage return'})).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox',{name:'Lotto experiment'}),{target:{value:'put-fixed5'}});
  await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/lotto-paper-trials?page=1&account_key=put-fixed5'));
  expect(screen.getByText(/Never add these balances together/)).toBeInTheDocument();
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
  expect(fetch).toHaveBeenCalledWith('/api/lotto-paper-trials?page=2');
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
