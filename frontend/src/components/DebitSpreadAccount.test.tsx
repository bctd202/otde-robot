import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {DebitSpreadAccount} from './DebitSpreadAccount';
import {getDebitSpreadAccount} from '../api/client';
import type {DebitSpreadAccountData} from '../types';
vi.mock('../api/client',()=>({getDebitSpreadAccount:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks()});
const base:DebitSpreadAccountData={account_key:'debit-vertical-v1',status:'NOT_ACTIVATED',enabled:false,
  paper_only:true,baseline_account:'tasty-capacity-ten-v1',starting_cash_cents:200000};

test('inactive research panel makes no request',()=>{
  render(<DebitSpreadAccount/>);expect(getDebitSpreadAccount).not.toHaveBeenCalled();
});
test('unactivated view never invents a funded balance or historical return',async()=>{
  vi.mocked(getDebitSpreadAccount).mockResolvedValue(base);render(<DebitSpreadAccount active/>);
  expect(await screen.findByText('Prepared · not activated')).toBeVisible();
  expect(screen.getByText(/No money has been funded/)).toBeVisible();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});
test('unknown value remains incomplete and unresolved pairs remain in comparison',async()=>{
  vi.mocked(getDebitSpreadAccount).mockResolvedValue({...base,status:'ACTIVE',enabled:true,
    equity_cents:null,available_cents:null,unknown_positions:1,held_positions:1,pending_positions:0,
    settled_cents:196000,unsettled_cents:0,realized_cents:0,skips:2,page:1,pages:2,positions:[],
    history:[{at:'2026-11-09T15:00:00Z',equity_cents:200000,cash_cents:200000,unknown:0},
      {at:'2026-11-09T15:01:00Z',equity_cents:null,cash_cents:196000,unknown:1}],
    matched:{entered_pairs:1,closed_priced_pairs:0,unresolved_pairs:1,complete:false,
      spread_closed_subset_pnl_cents:0,baseline_closed_subset_pnl_cents:0}});
  render(<DebitSpreadAccount active/>);
  expect(await screen.findByText('Account value incomplete')).toBeVisible();
  fireEvent.click(screen.getByText('Matched comparison with the main account'));
  expect(screen.getByText(/1 matched entries · 0 closed and priced pairs · 1 unresolved pairs/)).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Return %'}));
  expect(screen.getByRole('button',{name:'Return %'})).toHaveAttribute('aria-pressed','true');
  expect(screen.getByText('Account value incomplete')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(getDebitSpreadAccount).toHaveBeenLastCalledWith(2);
});

test('known account return uses its starting cash and changing graph views never changes accounts',async()=>{
  vi.mocked(getDebitSpreadAccount).mockResolvedValue({...base,status:'ACTIVE',enabled:true,
    equity_cents:220000,available_cents:220000,settled_cents:220000,unsettled_cents:0,
    realized_cents:20000,unknown_positions:0,held_positions:0,pending_positions:0,
    skips:0,page:1,pages:1,positions:[],history:[
      {at:'2026-11-09T20:00:00Z',equity_cents:200000,cash_cents:200000,unknown:0},
      {at:'2026-11-10T20:00:00Z',equity_cents:220000,cash_cents:220000,unknown:0}]});
  render(<DebitSpreadAccount active/>);await screen.findByRole('img');
  fireEvent.click(screen.getByRole('button',{name:'Return %'}));
  expect(screen.getByRole('heading',{name:'10.00%'})).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'1D'}));
  expect(screen.getByText(/Latest recorded day/)).toBeVisible();
  expect(getDebitSpreadAccount).toHaveBeenCalledTimes(1);
});
