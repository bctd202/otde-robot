import { describe, expect, test } from 'vitest';

import { generateMockCandles } from './CandlestickChart';

describe('generateMockCandles', () => {
  test('creates 150 deterministic one-minute OHLC candles ending at the current price', () => {
    const first = generateMockCandles('SPY', 551.6);
    const second = generateMockCandles('SPY', 551.6);

    expect(first).toHaveLength(150);
    expect(first).toEqual(second);
    expect(first.at(-1)?.close).toBeCloseTo(551.6, 8);
    expect(Number(first[1].time) - Number(first[0].time)).toBe(60);
    first.forEach((candle) => {
      expect(candle.high).toBeGreaterThanOrEqual(Math.max(Number(candle.open), Number(candle.close)));
      expect(candle.low).toBeLessThanOrEqual(Math.min(Number(candle.open), Number(candle.close)));
    });
  });
});
