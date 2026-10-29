import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {AccountDirectory} from './AccountDirectory';
import {ForwardPaperAccount} from './ForwardPaperAccount';
import {LottoForward} from './LottoForward';
import {RetestResearch} from './RetestResearch';

afterEach(()=>{cleanup();vi.restoreAllMocks();window.history.replaceState(null,'','/')});

test('directory links all eight accounts without inventing balances or making requests',()=>{
  window.history.replaceState(null,'','/?v=release&paper_account=old#parlay');
  const fetch=vi.spyOn(globalThis,'fetch');
  render(<AccountDirectory/>);
  const links=screen.getAllByRole('link',{hidden:true});
  expect(links).toHaveLength(8);expect(fetch).not.toHaveBeenCalled();
  const newAccount=new URL(links[0].getAttribute('href')!,'http://localhost');
  expect(newAccount.searchParams.get('paper_account')).toBe('tasty-capacity-ten-v1');
  expect(newAccount.searchParams.get('v')).toBe('release');
  expect(newAccount.hash).toBe('#performance');
  const lotto=new URL(screen.getByRole('link',{name:/Lotto · trail after 2×/,hidden:true}).getAttribute('href')!,'http://localhost');
  expect(lotto.searchParams.has('paper_account')).toBe(false);
  expect(lotto.searchParams.get('lotto_account')).toBe('lotto-v3-contract100-multi5-trail40');
  expect(lotto.hash).toBe('#lottery');
});

test('main is immediately visible; experiments and history are collapsed without disabling accounts',()=>{
  render(<AccountDirectory/>);
  expect(screen.getByRole('link',{name:/Main · ten positions/})).toBeVisible();
  const experiments=screen.getByText('Experiments').closest('details')!;
  const history=screen.getByText('History').closest('details')!;
  expect(experiments).not.toHaveAttribute('open');
  expect(history).not.toHaveAttribute('open');
  const lotto=screen.getByRole('link',{name:/Lotto · 5× exit/,hidden:true});
  const original=screen.getByRole('link',{name:/Original · three positions/,hidden:true});
  expect(lotto).not.toBeVisible();expect(original).not.toBeVisible();
  fireEvent.click(screen.getByText('Experiments'));
  expect(lotto).toBeVisible();
  expect(within(experiments).getAllByRole('link')).toHaveLength(6);
  expect(original).not.toBeVisible();
  fireEvent.click(screen.getByText('History'));
  expect(original).toBeVisible();
  expect(screen.getByText(/not stopped, reset or settled/)).toBeVisible();
});

test('every account link clears other account selections and retains the release marker',()=>{
  window.history.replaceState(null,'','/?v=release&paper_account=old&lotto_account=old&research_account=old#parlay');
  render(<AccountDirectory/>);
  const keys=['paper_account','lotto_account','research_account'];
  for(const link of screen.getAllByRole('link',{hidden:true})){
    const url=new URL(link.getAttribute('href')!,'http://localhost');
    expect(keys.filter(key=>url.searchParams.has(key))).toHaveLength(1);
    expect(url.searchParams.get('v')).toBe('release');
  }
});

test('main account link opens requested preserved account, not the new default',async()=>{
  window.history.replaceState(null,'','/?paper_account=tasty-session-v2-20261019#performance');
  const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({status:'NOT_STARTED',paper_only:true})));
  render(<ForwardPaperAccount/>);
  await screen.findByText(/Not started/);
  expect(fetch).toHaveBeenCalledWith('/api/forward-paper-account?page=1&account_key=tasty-session-v2-20261019');
});

test('lotto directory link requests exact exit-rule account',async()=>{
  window.history.replaceState(null,'','/?lotto_account=lotto-v3-contract100-multi5-trail40#lottery');
  const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}'));
  render(<LottoForward onInspect={()=>{}}/>);
  await screen.findByRole('alert');
  expect(fetch).toHaveBeenCalledWith('/api/lotto-paper-trials?page=1&account_key=lotto-v3-contract100-multi5-trail40&view=ENTERED');
});

test('research directory link selects treatment stress chart without combining accounts',async()=>{
  window.history.replaceState(null,'','/?research_account=breakout-retest-v1%3Atreatment%3Astress#backtest-lab');
  vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({status:'COLLECTING',note:'Synthetic',
    accounts:[{key:'control',arm:'control',scenario:'base',daily:[]},
      {key:'breakout-retest-v1:treatment:stress',arm:'treatment',scenario:'stress',daily:[]}]})));
  render(<RetestResearch active/>);
  expect(await screen.findByRole('combobox',{name:'Independent account'})).toHaveValue('breakout-retest-v1:treatment:stress');
  expect(screen.getByText('Wait for retest — observed account value')).toBeVisible();
});
