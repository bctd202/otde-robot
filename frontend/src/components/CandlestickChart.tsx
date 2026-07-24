import { useEffect, useMemo, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts';

import {
  buildLiquidityLevels,
  detectLiquidityEvents,
  nearestLevelAbove,
  nearestLevelBelow,
  primaryLiquidityTarget,
  scoreLiquiditySetup,
  type ChartLiquidityLevel,
  type LiquidityEvent,
} from '../lib/liquidity';
import type { LiquidityLevels } from '../types';

interface CandlestickChartProps {
  symbol: string;
  currentPrice: number;
  levels: LiquidityLevels;
  directionalBias: string;
}

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

export function generateMockCandles(symbol: string, currentPrice: number, count = 150): CandlestickData[] {
  const symbolSeed = [...symbol].reduce((total, character) => total + character.charCodeAt(0), 0);
  const random = seededRandom(symbolSeed * 1009 + count);
  const startTime = Math.floor(Date.UTC(2026, 6, 17, 13, 30) / 1000);
  const candles: CandlestickData[] = [];
  let previousClose = currentPrice - 0.85;

  for (let index = 0; index < count; index += 1) {
    const trend = 0.008 + Math.sin(index / 17) * 0.018;
    const impulse = (random() - 0.49) * 0.32;
    const open = previousClose + (random() - 0.5) * 0.06;
    const close = open + trend + impulse;
    const wick = 0.05 + random() * 0.16;
    const high = Math.max(open, close) + wick;
    const low = Math.min(open, close) - (0.05 + random() * 0.16);

    candles.push({
      time: (startTime + index * 60) as UTCTimestamp,
      open,
      high,
      low,
      close,
    });
    previousClose = close;
  }

  const adjustment = currentPrice - Number(candles.at(-1)?.close ?? currentPrice);
  return candles.map((candle) => ({
    ...candle,
    open: Number(candle.open) + adjustment,
    high: Number(candle.high) + adjustment,
    low: Number(candle.low) + adjustment,
    close: Number(candle.close) + adjustment,
  }));
}

function addDeterministicSweepExamples(
  candles: CandlestickData[],
  liquidityLevels: ChartLiquidityLevel[],
): CandlestickData[] {
  const result = candles.map((candle) => ({ ...candle }));
  const highLevel = liquidityLevels.find((level) => level.label === 'ORH')
    ?? liquidityLevels.find((level) => level.side === 'high');
  const lowLevel = liquidityLevels.find((level) => level.label === 'ORL')
    ?? liquidityLevels.find((level) => level.side === 'low');

  if (highLevel && result.length > 102) {
    result[100] = { ...result[100], open: highLevel.price - 0.12, high: highLevel.price + 0.18, low: highLevel.price - 0.24, close: highLevel.price - 0.08 };
    result[101] = { ...result[101], open: highLevel.price - 0.07, high: highLevel.price - 0.02, low: highLevel.price - 0.24, close: highLevel.price - 0.14 };
  }
  if (lowLevel && result.length > 122) {
    result[120] = { ...result[120], open: lowLevel.price + 0.12, high: lowLevel.price + 0.24, low: lowLevel.price - 0.18, close: lowLevel.price + 0.08 };
    result[121] = { ...result[121], open: lowLevel.price + 0.07, high: lowLevel.price + 0.24, low: lowLevel.price + 0.02, close: lowLevel.price + 0.14 };
  }
  return result;
}

function levelAppearance(level: ChartLiquidityLevel): { color: string; lineStyle: LineStyle } {
  if (level.label === 'VWAP') return { color: '#c084fc', lineStyle: LineStyle.Dotted };
  if (level.label.startsWith('OR')) return { color: '#f5b942', lineStyle: LineStyle.Dashed };
  if (level.label === 'HOD' || level.label === 'LOD') return { color: '#4bd5a9', lineStyle: LineStyle.SparseDotted };
  if (level.label === 'EQH') return { color: '#38bdf8', lineStyle: LineStyle.Dashed };
  if (level.label === 'EQL') return { color: '#fb7185', lineStyle: LineStyle.Dashed };
  return { color: '#60a5fa', lineStyle: LineStyle.Solid };
}

function markerForEvent(event: LiquidityEvent): SeriesMarker<UTCTimestamp> {
  const isHigh = event.side === 'high';
  return {
    time: event.timestamp as UTCTimestamp,
    position: isHigh ? 'aboveBar' : 'belowBar',
    shape: isHigh ? 'arrowDown' : 'arrowUp',
    color: event.eventType === 'reclaim' ? '#f5b942' : isHigh ? '#f06472' : '#36d6a3',
    text: event.eventType === 'sweep'
      ? `${event.levelLabel} SWEEP`
      : `${event.direction === 'bullish' ? 'BULLISH' : 'BEARISH'} RECLAIM`,
  };
}

function distanceText(currentPrice: number, level: ChartLiquidityLevel | null): string {
  if (!level) return 'None';
  const points = Math.abs(level.price - currentPrice);
  const percent = currentPrice ? points / currentPrice * 100 : 0;
  return `${level.label} ${level.price.toFixed(2)} · ${points.toFixed(2)} pts (${percent.toFixed(2)}%)`;
}

function eventTime(timestamp: number): string {
  return new Intl.DateTimeFormat('en-US', {
    hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York',
  }).format(new Date(timestamp * 1000));
}

export function CandlestickChart({ symbol, currentPrice, levels, directionalBias }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const liquidityLevels = useMemo(() => buildLiquidityLevels(levels), [levels]);
  const candles = useMemo(
    () => addDeterministicSweepExamples(generateMockCandles(symbol, currentPrice), liquidityLevels),
    [symbol, currentPrice, liquidityLevels],
  );
  const events = useMemo(() => detectLiquidityEvents(symbol, candles.map((candle) => ({
    time: Number(candle.time),
    open: Number(candle.open), high: Number(candle.high), low: Number(candle.low), close: Number(candle.close),
  })), liquidityLevels), [symbol, candles, liquidityLevels]);
  const nearestAbove = nearestLevelAbove(currentPrice, liquidityLevels);
  const nearestBelow = nearestLevelBelow(currentPrice, liquidityLevels);
  const primaryTarget = primaryLiquidityTarget(currentPrice, liquidityLevels, directionalBias);
  const score = scoreLiquiditySetup(events, currentPrice, liquidityLevels, directionalBias);
  const recentEvents = [...events].reverse().slice(0, 5);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 340,
      layout: { background: { type: ColorType.Solid, color: '#090f18' }, textColor: '#91a0b5', fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif' },
      grid: { vertLines: { color: '#172231' }, horzLines: { color: '#172231' } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: '#718096', labelBackgroundColor: '#253348' }, horzLine: { color: '#718096', labelBackgroundColor: '#253348' } },
      rightPriceScale: { borderColor: '#263244', scaleMargins: { top: 0.12, bottom: 0.12 } },
      timeScale: { borderColor: '#263244', timeVisible: true, secondsVisible: false, rightOffset: 4, barSpacing: 6 },
      handleScroll: true,
      handleScale: true,
      kineticScroll: { touch: true, mouse: true },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#36d6a3', downColor: '#f06472', borderUpColor: '#36d6a3', borderDownColor: '#f06472',
      wickUpColor: '#64e8bb', wickDownColor: '#f58a95', priceLineVisible: false,
    });
    candleSeries.setData(candles);
    liquidityLevels.forEach((level) => candleSeries.createPriceLine({
      price: level.price,
      title: `${level.label} ${level.price.toFixed(2)}`,
      ...levelAppearance(level),
      lineWidth: 1,
      axisLabelVisible: true,
    }));
    createSeriesMarkers(candleSeries, events.map(markerForEvent));

    // FVG
    // Order Blocks
    // BOS
    // CHoCH

    chart.timeScale().fitContent();
    const resizeObserver = new ResizeObserver(([entry]) => chart.applyOptions({ width: Math.floor(entry.contentRect.width) }));
    resizeObserver.observe(container);
    return () => { resizeObserver.disconnect(); chart.remove(); };
  }, [candles, events, liquidityLevels]);

  return <div className="candlestick-workspace">
    <div className="chart-toolbar"><strong>{symbol}</strong><span>1m · deterministic mock candles</span></div>
    <div className="liquidity-status" aria-label="Liquidity context">
      <div><span>Current</span><strong>{currentPrice.toFixed(2)}</strong></div>
      <div><span>Nearest above</span><strong>{distanceText(currentPrice, nearestAbove)}</strong></div>
      <div><span>Nearest below</span><strong>{distanceText(currentPrice, nearestBelow)}</strong></div>
      <div><span>Bias</span><strong className={`direction-${directionalBias}`}>{directionalBias}</strong></div>
      <div><span>Primary target</span><strong>{primaryTarget ? `${primaryTarget.label} ${primaryTarget.price.toFixed(2)}` : 'None'}</strong></div>
      <div><span>Research score</span><strong>{score.value}/100 · {score.status}</strong></div>
    </div>
    <div ref={containerRef} className="candlestick-chart" aria-label={`${symbol} one-minute candlestick chart`} />
    <div className="liquidity-events">
      <h3>Recent Liquidity Events</h3>
      {recentEvents.length === 0 ? <p>No recent sweeps detected.</p> : recentEvents.map((event) =>
        <div className="liquidity-event" key={`${event.timestamp}-${event.levelType}-${event.eventType}`}>
          <time>{eventTime(event.timestamp)}</time><strong>{event.levelLabel} {event.levelPrice.toFixed(2)}</strong>
          <span>{event.eventType}</span><span className={`direction-${event.direction}`}>{event.direction}</span>
        </div>)}
      <small>Visual research score only — not a trade recommendation.</small>
    </div>
  </div>;
}
