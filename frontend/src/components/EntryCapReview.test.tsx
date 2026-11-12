import {cleanup,render,screen,fireEvent} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {EntryCapReview} from './EntryCapReview';
import type {EntryCapReviewData} from './EntryCapReview';
import {getEntryCapReview} from '../api/client';

vi.mock('../api/client',()=>({getEntryCapReview:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();window.history.replaceState(null,'','/')});
const comparison={cap_cents:12500,eligible:0,priced:0,positive:0,negative:0,flat:0,gaps:0,pending:0,
  average_net_cents:null,complete_quote_evidence:false};
const empty:EntryCapReviewData={current_cap_cents:10000,legacy_without_entry_receipt:12,recorded_skips:0,
  window_records:0,window_truncated:false,cap_only_records:0,comparisons:[comparison,{...comparison,cap_cents:15000}],
  rows:[],page:1,pages:1,limitation:'Independent opportunities, not a portfolio.'};
function open(data=empty){window.history.replaceState(null,'','/?review_caps=1');vi.mocked(getEntryCapReview).mockResolvedValue(data);render(<EntryCapReview active/>)}

test('collapsed or inactive view makes no requests',()=>{
  const first=render(<EntryCapReview active/>);expect(getEntryCapReview).not.toHaveBeenCalled();first.unmount();
  window.history.replaceState(null,'','/?review_caps=1');render(<EntryCapReview/>);
  expect(getEntryCapReview).not.toHaveBeenCalled();
});

test('legacy skips stay missing evidence and new empty sample has no invented profit chart',async()=>{
  open();expect(await screen.findByText('Current all-in entry cap: $100.00 · unchanged')).toBeVisible();
  expect(screen.getByText(/12 older price-limit skips/)).toBeVisible();
  expect(screen.getByText(/Collection starts with the next price-limit rejection/)).toBeVisible();
  expect(screen.getAllByText('No eligible prospective examples yet.')).toHaveLength(2);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:/activate|change|raise/i})).not.toBeInTheDocument();
});

test('losers and unknown outcomes remain visible with priced-subset averages',async()=>{
  open({...empty,recorded_skips:3,window_records:3,cap_only_records:3,
    comparisons:[{...comparison,eligible:3,priced:1,negative:1,gaps:1,pending:1,average_net_cents:-7000}]});
  expect(await screen.findByRole('img',{name:/1 negative, 0 flat, 2 open or missing/})).toBeVisible();
  expect(screen.getByText(/Average modeled P\/L per priced opportunity: -\$70.00/)).toBeVisible();
  expect(screen.getByText('1 still awaiting outcome · 1 missing exit evidence')).toBeVisible();
  expect(screen.getByText(/Missing outcomes are not counted as \$0/)).toBeVisible();
  expect(screen.getByText(/not account-value or portfolio-return graphs/)).toBeVisible();
});

test('untraded receipt has costs, later quote evidence and pagination without settings changes',async()=>{
  open({...empty,recorded_skips:21,window_records:21,pages:2,rows:[{id:1,at:'2026-11-11T14:46:12Z',
    ticker:'AAPL',right:'call',strike:355,expiration:'2026-11-11',option_symbol:'AAPL261111C00355000',
    cap_only:true,all_in_cents:10300,source_cap_cents:10000,entry_ask:1,status:'PRICED',net_pnl_cents:-7000,
    reason:null,entry_quote:{ask:1,receipt_basis:'REST_RESPONSE_RECEIVED_V1'},exit_quote:{bid:.34}}]});
  expect(await screen.findByText('AAPL CALL $355 · expires 2026-11-11')).toBeVisible();
  expect(screen.getByText('Modeled outcome after costs: -$70.00')).toBeVisible();
  fireEvent.click(screen.getByText('Inspect saved quote receipts'));
  expect(screen.getByText(/REST_RESPONSE_RECEIVED_V1/)).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(getEntryCapReview).toHaveBeenLastCalledWith(2);
});

test('a failure is displayed explicitly',async()=>{
  window.history.replaceState(null,'','/?review_caps=1');vi.mocked(getEntryCapReview).mockRejectedValue(new Error('offline'));
  render(<EntryCapReview active/>);expect(await screen.findByRole('alert')).toHaveTextContent('last saved response');
});
