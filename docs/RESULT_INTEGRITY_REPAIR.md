# Prospective result-integrity repair

This patch repairs paper measurement, candle chronology, replay qualification,
cost defaults and evidence labels. It does not enable brokerage orders, create or
reset accounts, tune entry scores, introduce trailing exits, change planned stops
or targets, switch providers, or rewrite historical results.

## New underlying benchmarks

New automated rows record `post-confirmation-quote-v1` in their existing JSON
snapshot. The entry benchmark is the observed underlying quote, not the breakout
trigger. Original trigger, stop, target, quote time and confirming-bar boundary
remain frozen and visible in the audit data. A quote already beyond the plan, an
invalid confirmation clock or a post-cutoff entry is unscorable. Even a zero-risk
first BUY remains an excluded first opportunity; a later winner cannot replace it.

This is a **research quote benchmark**, not proof of a stock or option fill.
Planned stop/target levels remain barrier assumptions. Actual option-dollar
simulation still requires its own fresh, later ask/bid evidence and costs.

Example with stop 99 and target 101.50:

| Entry convention | Entry | Target result | Exit at 100.20 |
|---|---:|---:|---:|
| Old trigger | 100.00 | +1.500R | +0.200R |
| New quote after confirmation | 100.40 | +0.786R | -0.143R |
| Better post-confirmation quote | 99.80 | +2.125R | +0.500R |

A worse entry reduces reward and can turn a small winner into a loser. Results
do not mechanically decrease in every case: a better quote can increase R.
Target-planning risk still uses the existing 0.2% floor; R uses saved entry-to-stop
distance. That distinction is preserved, not silently optimized.

## Entry-minute chronology and exit clocks

The cursor begins at the confirming minute, so the entry minute is inspected
when complete. For a quote at 10:30:04, the 10:30 candle contains four seconds
before entry. Its full high/low therefore cannot establish an after-entry hit.

- A wick-only level touch, or touches of both boundaries, is explicit unknown
  ordering (`DATA_GAP`), not a win, a guessed loss or a skipped minute.
- A close beyond just one boundary proves that side was reached after entry.
- First partial-minute excursion uses the close only; pre-entry extremes do not
  inflate MFE/MAE. An exact-minute benchmark can use the full entry bar.
- Missing required minutes remain gaps. A later candle cannot erase an earlier
  unknown stop/target path.
- New exits are timestamped at completed candle end; `last_evaluated_at` stays
  the candle-start cursor. Cash exits recognize the new clock without adding
  another minute. Legacy rows/positions keep their original convention.
- New cash admissions wait for current completed underlying evidence. Unknown
  entry-minute outcomes cancel pending admission; no replacement ticker-day fill.
- New cutoff handling uses the reviewed exchange calendar and early close.

No entry-bar tick ordering is reconstructed from OHLC candles. Higher-frequency
evidence and actual order handling remain future live-readiness work.

## Replay: full entry gate or explicit underlying-only observations

The full score/premium/no-chase/extension decision is a shared pure helper used
by production and replay. Production selection coefficients and conditions are
unchanged. Replay isolates each regular session, requires complete opening/entry
context, benchmarks the next consecutive same-session bar open, evaluates that
entry bar, and retains missing exits as unknown. It never substitutes a later day
or the last available close for missing execution evidence.

Historical BUY qualification also requires an archived, point-in-time contract
chain passing actual identity, expiration, spread, volume, OI, premium and score
checks. Current providers do not supply such archived chains through this
interface. Their stock-only replays therefore create `UNDERLYING_ONLY` rows,
excluded from strategy BUY metrics, with no invented full score or option P/L.
The UI labels these and old legacy replay runs explicitly. A completed replay
means the job finished, not that historical option execution was established.

## Costs and persisted-policy compatibility

One shared integer-cent helper supplies the existing ledger defaults:

- $1 opening commission, $0 closing commission;
- $0.50 fee allowance on each side;
- $0.01 premium slippage per share on each side, or $1 per 100-share contract.

The canonical name is `slippage_cents_per_share`. Historical
`slippage_premium_cents` policies remain byte-for-byte unchanged and are read by
a compatibility adapter. The contract multiplier is explicit. Conflicting unit
keys fail instead of silently creating a 100x cost error.

The read-only cost analysis now defaults to the same $2 fixed round-trip cost;
its former default omitted the $1 combined fee allowance. Thus its net and stress
figures fall by $1 per closed contract with otherwise identical assumptions.
Observed ask-to-bid marks and all saved cash entries remain unchanged.

For identical ask 0.45 / bid 0.75 quotes and multiplier 100: raw shadow +$30;
after $2 fixed costs +$28; after an additional one-cent-per-share slippage each
side +$26. The cash ledger's $47.50 debit and $73.50 net proceeds also give +$26.
Different actual quote timestamps need not produce equal P/L.

## Historical preservation and UI

Stored results are not re-entered, re-scored, backfilled or deleted. Read-only
measurement cohorts label legacy trigger versus new quote/open benchmarks.
The primary cash overview remains separate from underlying research R. Missing
prior-day levels are null, and the chart omits PDH/PDL instead of inventing padded
current-session levels. Existing true session high/low remain intact.

## Deployment handoff

1. Review the patch and required backend/frontend checks. Take and restore-check
   an off-machine database backup. Deploy the exact reviewed revision after hours
   using the existing project/branch workflow; no new accounts or migration.
2. Confirm old policy, cash-event, position and R fingerprints; verify fresh rows
   carry the new benchmark and completed-exit clock. Keep paper-only enabled.
3. The existing breakout/retest fingerprint intentionally blocks changed source.
   After review, append one zero-cash maintenance acknowledgment on the **same**
   run with `--scope existing-test-result-maintenance`, reviewed Git SHA, exact
   current code hash and original frozen hash. Never overwrite the original spec,
   fund replacement accounts, reset dates or automatically acknowledge on startup.
   See [maintenance procedure](RETEST_MAINTENANCE.md).
4. Verify readiness and research API agree that admissions are unblocked, original
   history and account balances are preserved, and next-open collection is enabled.
   The original uninterrupted-study verdict remains inconclusive after maintenance.

These repairs improve measurement integrity. They do not establish profitability
or make the app ready to place real orders.
