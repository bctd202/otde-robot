import { describe, expect, test } from 'vitest';

import {
  clampScore,
  detectLiquidityEvents,
  nearestLevelAbove,
  nearestLevelBelow,
  type ChartLiquidityLevel,
  type OhlcCandle,
} from './liquidity';

const levels: ChartLiquidityLevel[] = [
  { levelType: 'previous_day_low', label: 'PDL', price: 99, side: 'low' },
  { levelType: 'vwap', label: 'VWAP', price: 100, side: 'context' },
  { levelType: 'previous_day_high', label: 'PDH', price: 101, side: 'high' },
  { levelType: 'equal_high', label: 'EQH', price: 102, side: 'high' },
];

function candle(time: number, high: number, low: number, close: number): OhlcCandle {
  return { time, open: 100, high, low, close };
}

describe('liquidity context', () => {
  test('finds the nearest level above current price', () => {
    expect(nearestLevelAbove(100.25, levels)?.label).toBe('PDH');
  });

  test('finds the nearest level below current price', () => {
    expect(nearestLevelBelow(100.25, levels)?.label).toBe('VWAP');
  });
});

describe('liquidity event detection', () => {
  test('detects a bullish low-side sweep', () => {
    const events = detectLiquidityEvents('SPY', [candle(1, 100, 98.8, 99.2)], levels);
    expect(events).toContainEqual(expect.objectContaining({
      levelLabel: 'PDL', eventType: 'sweep', side: 'low', direction: 'bullish',
    }));
  });

  test('detects a bearish high-side sweep', () => {
    const events = detectLiquidityEvents('SPY', [candle(1, 101.2, 100, 100.8)], levels);
    expect(events).toContainEqual(expect.objectContaining({
      levelLabel: 'PDH', eventType: 'sweep', side: 'high', direction: 'bearish',
    }));
  });

  test('confirms a bullish reclaim on the following candle', () => {
    const events = detectLiquidityEvents('SPY', [
      candle(1, 100, 98.8, 99.2),
      candle(2, 100, 99.1, 99.6),
    ], levels);
    expect(events).toContainEqual(expect.objectContaining({
      timestamp: 2, levelLabel: 'PDL', eventType: 'reclaim', direction: 'bullish',
    }));
  });

  test('confirms a bearish reclaim on the following candle', () => {
    const events = detectLiquidityEvents('SPY', [
      candle(1, 101.2, 100, 100.8),
      candle(2, 100.9, 100.2, 100.6),
    ], levels);
    expect(events).toContainEqual(expect.objectContaining({
      timestamp: 2, levelLabel: 'PDH', eventType: 'reclaim', direction: 'bearish',
    }));
  });
});

test('liquidity score clamps between zero and one hundred', () => {
  expect(clampScore(-25)).toBe(0);
  expect(clampScore(54.6)).toBe(55);
  expect(clampScore(140)).toBe(100);
});
