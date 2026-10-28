import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {RetestResearch,type RetestResponse} from './RetestResearch';
import {getRetestResearch} from '../api/client';
vi.mock('../api/client',()=>({getRetestResearch:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks()});

test('inactive pane makes no request and unactivated experiment has no funding or activation button',async()=>{
  vi.mocked(getRetestResearch).mockResolvedValue({status:'NOT_ACTIVATED',note:'Separate activation approval required.'});
  const {rerender}=render(<RetestResearch active={false}/>);
  expect(getRetestResearch).not.toHaveBeenCalled();rerender(<RetestResearch active/>);
  expect(await screen.findByText('Not activated')).toBeVisible();
  expect(screen.queryByRole('button',{name:/activate/i})).not.toBeInTheDocument();
  expect(screen.queryByText('$2,000.00')).not.toBeInTheDocument();
});

const fixture:RetestResponse={status:'COLLECTING',note:'Paper evidence, not brokerage fills.',verdict:'INCONCLUSIVE',
  baseline_opportunities:4,input_coverage:98,accounts:[{key:'base-control',arm:'control',scenario:'base',complete:false,
    net_pnl_cents:null,max_drawdown_cents:null,unresolved:1,entry_quote_coverage:90,exit_quote_coverage:null,
    daily:[{date:'2026-10-27',equity_cents:200000,complete:false},{date:'2026-10-28',equity_cents:null,complete:false},
      {date:'2026-10-29',equity_cents:199000,complete:false}]}],
  latest:{at:'2026-10-29',accounts:{'base-control':{equity_cents:null}}},
  positions:[{id:1,ticker:'SPY',arm:'treatment',scenario:'base',status:'SKIPPED',detail:{reason:'CAPACITY_SKIP',net_pnl_cents:null}}],
  pagination:{page:1,pages:2,total:24}};

test('unknown values stay unknown, graph gaps are not joined, and pagination is read-only',async()=>{
  vi.mocked(getRetestResearch).mockResolvedValue(fixture);
  const {container}=render(<RetestResearch active/>);
  expect(await screen.findByText('Collecting — no conclusion yet')).toBeVisible();
  expect(screen.getByText('INCONCLUSIVE')).toBeVisible();expect(screen.getByText('Unknown')).toBeVisible();
  expect(container.querySelectorAll('polyline')).toHaveLength(2);
  expect(container.querySelectorAll('circle')).toHaveLength(2);
  expect(screen.getByText('CAPACITY SKIP')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  await waitFor(()=>expect(getRetestResearch).toHaveBeenLastCalledWith(2,'accounts'));
  fireEvent.click(await screen.findByRole('button',{name:'Uncapped opportunities'}));
  await waitFor(()=>expect(getRetestResearch).toHaveBeenLastCalledWith(1,'opportunities'));
  expect(await screen.findByText(/ignore cash\/slot limits/)).toBeVisible();
});

test('fetch failure is explicit, never a zero return',async()=>{
  vi.mocked(getRetestResearch).mockRejectedValue(new Error('Unavailable'));
  render(<RetestResearch active/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable');
  expect(screen.queryByText('$0.00')).not.toBeInTheDocument();
});

test('prominent uncapped research action uses existing read-only records without changing accounts',async()=>{
  vi.mocked(getRetestResearch).mockResolvedValue(fixture);
  render(<RetestResearch active/>);
  fireEvent.click(await screen.findByRole('button',{name:'Explore uncapped records'}));
  await waitFor(()=>expect(getRetestResearch).toHaveBeenLastCalledWith(1,'opportunities'));
  expect(await screen.findByText('Opportunity observations · both arms')).toBeVisible();
  expect(screen.getByText(/24 saved decision rows, not a count of unique trades/)).toBeVisible();
  expect(screen.getByText(/first-opportunity selection, quote deadlines and verification still apply/)).toBeVisible();
});
