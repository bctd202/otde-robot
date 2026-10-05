import { expect, test } from 'vitest';
import { isVerifiedLiveContract } from './contracts';

const base={option_symbol:'SPY260902C00100000',bid:.2,ask:.22,volume:1000,open_interest:1500,
  delta:.15,gamma:.04,actionable:true,verification_status:'verified',data_mode:'live',
  normalized_symbol:'SPY260902C00100000',bid_timestamp:'2026-09-02T14:05:00Z',
  ask_timestamp:'2026-09-02T14:05:00Z',timestamp:'2026-09-02T14:05:00Z'};

test('accepts only approved verified live providers',()=>{
  expect(isVerifiedLiveContract({...base,provider:'tastytrade'})).toBe(true);
  expect(isVerifiedLiveContract({...base,provider:'tradier'})).toBe(true);
  expect(isVerifiedLiveContract({...base,provider:'unknown'})).toBe(false);
  expect(isVerifiedLiveContract({...base,provider:'tastytrade',data_mode:'delayed'})).toBe(false);
});
