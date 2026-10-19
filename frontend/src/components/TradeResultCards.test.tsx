import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,test} from 'vitest';
import {TradeResultCards,tradeOutcome} from './TradeResultCards';
import type {MoneyTrade} from '../types';

afterEach(cleanup);
const trade=(overrides:Partial<MoneyTrade>={}):MoneyTrade=>({id:1,status:'CLOSED',option_symbol:'SPY test call',entry_debit_cents:2000,net_proceeds_cents:5000,...overrides});

test('net cash multiple and percentage use the same cost basis, not the underlying',()=>{
  expect(tradeOutcome(trade())).toMatchObject({pnl:3000,percent:150,multiple:2.5});
  expect(tradeOutcome(trade({net_proceeds_cents:4000}))).toMatchObject({percent:100,multiple:2});
  expect(tradeOutcome(trade({net_proceeds_cents:0}))).toMatchObject({percent:-100,multiple:0});
  expect(tradeOutcome(trade({net_proceeds_cents:-50}))).toMatchObject({pnl:-2050,multiple:-.025});
  expect(tradeOutcome(trade({net_proceeds_cents:null}))).toBeNull();
  expect(tradeOutcome(trade({entry_debit_cents:0}))).toBeNull();
});

test('cards show cash flow and one outcome unit at a time',()=>{
  render(<TradeResultCards trades={[trade()]}/>);
  expect(screen.getByText('gain $30.00 · +150.0%')).toBeInTheDocument();
  expect(screen.getByText('$20.00')).toBeInTheDocument();
  expect(screen.getByText('$50.00')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Money back ×'}));
  expect(screen.getByText('gain $30.00 · 2.50× returned')).toBeInTheDocument();
  expect(screen.queryByText('+150.0%')).not.toBeInTheDocument();
});

test('open marks are estimates and missing exits never become zero returns',()=>{
  const open=trade({status:'OPEN',estimated_net_proceeds_cents:1500});
  expect(tradeOutcome(open)).toMatchObject({closed:false,pnl:-500,percent:-25});
  expect(tradeOutcome(trade({status:'UNPRICED'}))).toBeNull();
  render(<TradeResultCards trades={[open,trade({id:2,status:'UNPRICED'})]}/>);
  expect(screen.getByText('Estimated loss $5.00 · -25.0%')).toBeInTheDocument();
  expect(screen.getByText('Result unknown — missing price evidence')).toBeInTheDocument();
  expect(screen.queryByText('-100.0%')).not.toBeInTheDocument();
});

test('OCC symbols have a human-readable direction, strike and expiration',()=>{
  render(<TradeResultCards trades={[trade({option_symbol:'SPY   261019P00760000'})]}/>);
  expect(screen.getByText('SPY PUT $760 · 10/19/2026')).toBeInTheDocument();
});
