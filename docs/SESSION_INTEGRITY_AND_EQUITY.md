# Session integrity and account-value history

This patch corrects live research inputs and adds observed account-value history.
It does not add brokerage execution, change scanner contract filters, remove
tickers, alter stop/target formulas, or recalculate old plays. The follow-up
[corrected trial](CORRECTED_TRIAL.md) isolates new Tastytrade evidence in a
separate account; it does not transfer or erase the legacy account's exposure.

## Current-session boundary

- Tastytrade candle caches rotate by exchange session and stream generation.
  A stopped stream cannot repopulate the cache, including on a same-day reconnect.
  Overnight/weekend/holiday rollover and configured early closes are respected.
- One-minute, structured intraday, and lottery entry inputs are restricted to the
  current regular session and completed-candle boundary. Prior-session bars cannot
  satisfy the existing 8-, 60-, or 12-bar requirements.
- New main/structured decisions carry `*-session-v2` versions and saved
  `input_evidence`: session date, evaluation boundary, candle count, first/last
  timestamps, opening range, and VWAP. Lottery initial snapshots preserve the
  same evidence. Existing strategy snapshots remain unchanged.
- Performance displays separate session-isolated and legacy input cohorts.
  "Legacy" means not revalidated; it does not assert that every older play was
  affected. The original headline arithmetic is preserved.

## Independent close housekeeping

The scanner retains its original close run. An independent close job at the
exchange close +15 seconds has its own scheduler slot, waits for the scan lock,
and performs no market requests. It closes lottery lifecycle records, advances
normal account reconciliation, expires stale alerts, and closes the background
provider. It honors operator holds, early closes, weekends, and holidays; startup
also reconciles previous-session rows. It does not fabricate an option exit.

## Forward account graph

Migration `0015_forward_equity` adds an append-only observation table. It does not
modify existing balances, funding, cash events, positions, or signal records.

Each processed account observation saves:

- Cash = settled cash + unsettled sale proceeds.
- Liquidation equity = cash + verified open-contract bid values, less the existing
  modeled exit slippage and closing costs. Entry costs have already reduced cash.
- Return = (liquidation equity − original funding) / original funding × 100.

If any held position is unpriced, total equity and return are null, not zero and
not purchase cost. Explicit verified zero bids remain valid evidence. Reads do
not create or backfill observations. Duplicate ticks cannot replace saved marks.
Settlement only moves cash between buckets; it is not a profit event.

The graph offers percentage/dollar units and 1D/1W/1M/ALL ranges. All returns use
the original funding baseline; range controls do not rebase the return. 1D shows
the latest recorded day's observations, while longer ranges use the last saved
observation each day. Unknown valuations and intraday collection gaps longer than
three minutes break the line. An empty history is explicitly labeled. The
existing account is not reset: earlier cash events can still affect current
equity, and unresolved historical exposure remains unknown.

The corrected trial receives exactly $2,000 once, no earlier than October 19,
2026 at 09:30 Eastern. Its initial observation records 0%; it does not backdate
activation if deployment is late. Existing accounts keep their frozen funding,
balances, policy and positions in the read-only legacy view. Lotto and manual
trades stay separate. This is modeled paper equity, not broker-confirmed account
performance.

## Backtesting data limitation

Funding a brokerage account is not equivalent to obtaining an expired-options
historical quote archive. Tradier's [historical data documentation](https://docs.tradier.com/docs/historical-data)
states that expired options' historical data is unavailable. Realistic historical
0DTE execution research needs exact-contract timestamped bid/ask history (and
ideally sizes), plus explicit fees, slippage, timing, and capital rules. Stock
candles or daily option OHLC cannot supply missing historical executable quotes.
No provider switch or funding action is included in this patch.

## Verification

Regression tests cover session rollover, superseded callbacks, early-open
eligibility, input evidence, independent close scheduling and early closes,
preservation of old ledger data during migration, equity/return arithmetic,
settlement invariance, missing-price gaps, idempotence, read-only API summaries,
and frontend units/ranges/inspection controls.

Local verification on 2026-10-17: 212 backend tests and 66 frontend tests passed;
Ruff, Mypy, ESLint, TypeScript and the frontend production build passed. Chrome
checks with synthetic account fixtures passed at desktop, 390px and 320px widths,
including unknown-value gaps and the dollar/percentage controls. A container
build and production deployment have not been verified as part of this patch.
