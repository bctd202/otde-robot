# How the one-minute strategy works

This describes the existing `parlay-v1` rules, not a newly optimized strategy.
“One-minute” means the candle timeframe, not the holding period. Signals remain paper-only.

## Entry sequence

1. Require at least eight completed one-minute candles, including the most recent completed minute.
2. Evaluate six directional checks: price relative to session VWAP, a VWAP crossing, the five-bar opening range, the previous seven bars' high/low, price acceleration, and volume exceeding the previous three-bar average. Calls and puts use opposite price checks; increasing volume supports either direction. The winning direction needs at least three checks and a lead of two.
3. Set the call trigger at the greater of the opening-range high and recent high; put trigger at the lesser of their lows. A completed close must break that trigger.
4. Require an authentic, explicitly live same-day option: ask $0.20–$1.00, positive bid, no crossed market, spread at most 20% of midpoint, volume at least 250, open interest at least 500, and bid/ask freshness checks. Call strike must not exceed the underlying target; put strike must not be below it. Eligible contracts rank by volume plus half open interest, with tighter spread breaking ties. The cheapest contract is not automatically selected.
5. Compute `score = clamp(42 + 8*checks + min(volume/250,8) + min(open_interest/1000,4) - spread_percent/4, 0, 100)`. BUY requires at least 85, a confirmed breakout, ask within the entry band, and extension no greater than 1.35 target-planning risk units. A confirmed but overextended/overpriced setup becomes MISSED. Otherwise a score of 70 or more can remain WATCH.

The entry band's preferred premium is the lesser of midpoint and positive last price (otherwise midpoint). Its upper bound is `min($1, preferred*1.08)`, rounded to cents. The separate no-chase ceiling is `min($1.25, max(entry_high+$0.05, preferred*1.25))`. These are unchanged existing rules.

## Exits and R

- Call invalidation is the lesser of VWAP and opening-range high; put invalidation is the greater of VWAP and opening-range low.
- Target-planning distance is the larger of trigger-to-invalidation distance and 0.2% of underlying price. First target is 1.5 times that distance; the displayed stretch target uses 2.5 times it.
- The automated underlying ledger resolves at the saved stop, first target, or completed 3:45 PM ET candle. If one candle touches both stop and target, stop takes precedence. Gaps remain exclusions rather than invented fills.
- Recorded R divides the direction-adjusted underlying move by the **actual saved trigger-to-stop distance**, not the minimum target-planning distance. Thus targets can resolve above 1.5R. Prices are rounded when the plan is saved.
- Displayed option-premium targets do not drive these underlying exits. The separate option shadow uses the entry ask and the first verified bid after the underlying exit. It is quote evidence, not a broker fill or live account.
- The normal performance view selects the first automated BUY per ticker/day and then applies quality exclusions. Manual journal links do not remove automated origin. The option-shadow slot remains shared across the two engines; this patch does not increase exposure or change selection.

## What this patch tests

We preserve the baseline and collect new accepted-contract bid/ask paths from the scanner cache. Fixed 15-, 30-, and 60-minute maximum holds are compared with baseline on matching, fully quoted plays. An earlier baseline exit is retained. Missing horizon quotes are explicitly incomplete, not zero-dollar exits. No historical option paths are reconstructed.

The next decision is whether a specific rule improves **net option dollars** on new data—not whether it increases the displayed R or cherry-picks a peak. The existing SPY/QQQ/IWM comparison and separate lotto experiment remain visible. No ticker is removed, score lowered, stop widened, or live order enabled here.

See [research accounting and verification](RESEARCH_ACCOUNTING.md) for assumptions and known limitations.
