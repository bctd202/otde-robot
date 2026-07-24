import type { LiquidityLevels } from '../types';

export type LiquiditySide = 'high' | 'low';
export type LiquidityEventType = 'sweep' | 'reclaim';
export type LiquidityDirection = 'bullish' | 'bearish';

export interface OhlcCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface ChartLiquidityLevel {
  levelType: string;
  label: string;
  price: number;
  side: LiquiditySide | 'context';
}

export interface LiquidityEvent {
  timestamp: number;
  symbol: string;
  levelType: string;
  levelLabel: string;
  levelPrice: number;
  side: LiquiditySide;
  eventType: LiquidityEventType;
  direction: LiquidityDirection;
}

export interface LiquidityScore {
  value: number;
  status: 'No Setup' | 'Developing' | 'Qualified' | 'High Confluence';
}

const DUPLICATE_TOLERANCE = 0.01;

export function buildLiquidityLevels(levels: LiquidityLevels): ChartLiquidityLevel[] {
  const candidates: ChartLiquidityLevel[] = [
    { levelType: 'previous_day_high', label: 'PDH', price: levels.previous_day_high, side: 'high' },
    { levelType: 'previous_day_low', label: 'PDL', price: levels.previous_day_low, side: 'low' },
    { levelType: 'opening_range_high', label: 'ORH', price: levels.opening_range_high, side: 'high' },
    { levelType: 'opening_range_low', label: 'ORL', price: levels.opening_range_low, side: 'low' },
    { levelType: 'session_high', label: 'HOD', price: levels.session_high, side: 'high' },
    { levelType: 'session_low', label: 'LOD', price: levels.session_low, side: 'low' },
    ...levels.equal_highs.map((price) => ({ levelType: 'equal_high', label: 'EQH', price, side: 'high' as const })),
    ...levels.equal_lows.map((price) => ({ levelType: 'equal_low', label: 'EQL', price, side: 'low' as const })),
    { levelType: 'vwap', label: 'VWAP', price: levels.vwap, side: 'context' },
  ];

  return candidates.filter((candidate, index) =>
    candidates.findIndex((other) => Math.abs(other.price - candidate.price) <= DUPLICATE_TOLERANCE) === index,
  );
}

export function nearestLevelAbove(currentPrice: number, levels: ChartLiquidityLevel[]): ChartLiquidityLevel | null {
  return levels
    .filter((level) => level.price > currentPrice)
    .sort((left, right) => left.price - right.price)[0] ?? null;
}

export function nearestLevelBelow(currentPrice: number, levels: ChartLiquidityLevel[]): ChartLiquidityLevel | null {
  return levels
    .filter((level) => level.price < currentPrice)
    .sort((left, right) => right.price - left.price)[0] ?? null;
}

export function detectLiquidityEvents(
  symbol: string,
  candles: OhlcCandle[],
  levels: ChartLiquidityLevel[],
): LiquidityEvent[] {
  const events: LiquidityEvent[] = [];
  const sweepLevels = levels.filter((level): level is ChartLiquidityLevel & { side: LiquiditySide } =>
    level.side !== 'context',
  );

  candles.forEach((candle, candleIndex) => {
    sweepLevels.forEach((level) => {
      const highSideSweep = level.side === 'high' && candle.high > level.price && candle.close < level.price;
      const lowSideSweep = level.side === 'low' && candle.low < level.price && candle.close > level.price;
      if (!highSideSweep && !lowSideSweep) return;

      const direction: LiquidityDirection = level.side === 'high' ? 'bearish' : 'bullish';
      events.push({
        timestamp: candle.time,
        symbol,
        levelType: level.levelType,
        levelLabel: level.label,
        levelPrice: level.price,
        side: level.side,
        eventType: 'sweep',
        direction,
      });

      const confirmation = candles[candleIndex + 1];
      const reclaimed = confirmation && (
        (level.side === 'high' && confirmation.close < level.price)
        || (level.side === 'low' && confirmation.close > level.price)
      );
      if (reclaimed) {
        events.push({
          timestamp: confirmation.time,
          symbol,
          levelType: level.levelType,
          levelLabel: level.label,
          levelPrice: level.price,
          side: level.side,
          eventType: 'reclaim',
          direction,
        });
      }
    });
  });

  return events.sort((left, right) => left.timestamp - right.timestamp);
}

export function clampScore(score: number): number {
  return Math.max(0, Math.min(100, Math.round(score)));
}

export function scoreLiquiditySetup(
  events: LiquidityEvent[],
  currentPrice: number,
  levels: ChartLiquidityLevel[],
  directionalBias: string,
): LiquidityScore {
  const latestSweep = [...events].reverse().find((event) => event.eventType === 'sweep');
  if (!latestSweep) return { value: 0, status: 'No Setup' };

  let score = 20;
  const reclaim = events.find((event) =>
    event.eventType === 'reclaim'
    && event.levelType === latestSweep.levelType
    && event.levelPrice === latestSweep.levelPrice
    && event.timestamp >= latestSweep.timestamp,
  );
  if (reclaim) score += 20;
  if (latestSweep.direction === directionalBias) score += 15;

  const vwap = levels.find((level) => level.levelType === 'vwap');
  if (vwap && Math.abs(currentPrice - vwap.price) / currentPrice <= 0.0025) score += 15;

  const risk = Math.max(Math.abs(currentPrice - latestSweep.levelPrice), 0.01);
  const target = latestSweep.direction === 'bullish'
    ? nearestLevelAbove(currentPrice, levels)
    : nearestLevelBelow(currentPrice, levels);
  if (target && Math.abs(target.price - currentPrice) >= risk * 2) score += 15;

  if (['PDH', 'PDL', 'ORH', 'ORL'].includes(latestSweep.levelLabel)) score += 15;

  const value = clampScore(score);
  const status = value >= 80 ? 'High Confluence'
    : value >= 60 ? 'Qualified'
      : value >= 40 ? 'Developing'
        : 'No Setup';
  return { value, status };
}

export function primaryLiquidityTarget(
  currentPrice: number,
  levels: ChartLiquidityLevel[],
  directionalBias: string,
): ChartLiquidityLevel | null {
  const above = nearestLevelAbove(currentPrice, levels);
  const below = nearestLevelBelow(currentPrice, levels);
  if (directionalBias === 'bullish') return above;
  if (directionalBias === 'bearish') return below;
  if (!above) return below;
  if (!below) return above;
  return above.price - currentPrice <= currentPrice - below.price ? above : below;
}
