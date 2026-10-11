# Research accounting and forward option paths

## Accounting corrections

- **Automated provenance:** Paper Enter journals a signal but no longer marks it manual-origin. Legacy flagged LIVE records are included only when linked to a paper position and carrying the known automated strategy/ticker/direction dedupe-key prefix. Other manually flagged records stay excluded. Manual option P/L remains out of automated ledger results. Existing flags and R values are not rewritten.
- **Cash chronology:** Strategy cash uses the later of mark event and observation time. Lotto cash replays all entries/exits in time order, rather than crediting a future exit before the next entry. Same-time entries run before exits, conservatively. An active lotto tracker may already have a target exit in a simulated target portfolio. Closing one position retains all other open debits in book equity.
- **Unpriced exposure:** Available cash is the headline; active debit, unresolved exit cost, and book equity are separate. Book equity carries unresolved contracts at cost, not an estimated liquidation price. The zero-value sensitivity removes unpriced exits from book value without fabricating fills. Strategy liquidation value is unknown while any position remains held.
- **Coverage and drawdown:** Show priced exits divided by all selected plays alongside the older terminal-tracked-entry coverage. Underlying R drawdown is entry-ordered, not option mark-to-market drawdown. Matched underlying metrics use the same closed option sample as the execution-cost panel.
- **Roundoff:** Cost-scenario win/loss/breakeven buckets are mutually exclusive using the existing `1e-9` breakeven tolerance; exact fee-adjusted breakeven must not also count as a loss.
- **Lotto fills:** Preserve gross first-bid 2×/5× replays. Add $1 total fixed-cost sensitivities and exact-target caps, which remove gains from a first quote jumping above a target. Those are assumptions, not broker fees or guaranteed limit fills. Entry fee is reserved immediately for cash sufficiency. Missing exit quotes never release cash. New observations reject stale, future, non-finite, wrong-identity, or non-live quotes using the actual collection clock; saved history is untouched.

## Forward experiment

Migration `0013_option_observations` adds one table; it does not backfill or modify signals, option entry/exit marks, lotto snapshots, or manual positions.

New automated signals freeze an `option-path-v1` definition with a code fingerprint, a safe configuration allowlist (provider, configured universe, flex limit, shadow enablement, exit quote lag, scan second), and fixed horizons. Existing per-signal fields retain entry date/time and exact provider/contract provenance. No secrets enter the snapshot. A different definition is excluded from the current experiment; changing a relevant setting requires the normal process restart so settings and the cached definition refresh together. The fingerprint covers the two strategy evaluators, performance service, and option research service, not every file in the repository.

After normal exit handling and existing lotto collection, observe accepted open contracts at most once per minute, with a cap of 40 per scan. Only same-trading-day entries with the new research version qualify. Use the existing fresh chain cache; **zero new provider requests**. Exact bid/ask timestamps must be within 60 seconds, no later than collection, and the bid must not predate entry observation. Explicit zero bids are valid; missing quotes are GAP records. A unique signal/minute constraint prevents duplicates after restart.

For each fixed maximum hold (15, 30, 60 minutes):

1. Require a resolved baseline and quoted entry/exit in the current frozen definition.
2. Keep the baseline exit if it was observed by the hold deadline.
3. Otherwise use the first saved, fresh bid timestamped at/after the deadline and observed within 90 seconds, no later than the baseline exit observation. If none exists, count the play incomplete.
4. Subtract the dashboard's fixed cost assumption from both exits and show both totals on exactly the same matched sample. Do not combine different horizon samples or treat missing cases as losses or winners.

Observations stop when the baseline underlying play closes. This supports earlier maximum holds, not arbitrary later exits. Cache expiry, scanner outages, and missing subscriptions can reduce coverage; no fresh quote is manufactured to complete a sample. This is exploratory, unconstrained one-contract exit research, **not** a second funded account, new trading rule, fill simulator, or live execution system. The existing cash portfolios retain their distinct assumptions.

## Snapshot verification: October 11, 2026

Tested migration and API replay on a temporary copy of `parlay-analysis-2026-10-11.sqlite`. Every original table's row content matched before and after; SQLite integrity passed and the new observation table was empty. The archival backup and production server were untouched. Saved eligible R sums/means reconcile to the API within rounding.

| View | Before journal repair | After repair |
| --- | ---: | ---: |
| One-minute total underlying R | +50.746R | +54.909R |
| One-minute quoted option P/L, before costs | −$685 | −$187 |
| One-minute priced option exits | 139 | 145 |
| Structured total underlying R | +10.575R | +10.575R |
| Structured quoted option P/L, before costs | −$27 | −$44 |

The six one-minute and two structured ticker-day substitutions now select the original automated BUY, not a later signal substituted after Paper Enter. This changes the selected cohort, **not** saved trade outcomes. One-minute quote coverage after repair is 145/229 selected plays (63.3%), versus 145/152 tracked terminal entries (95.4%). Its $1-cost scenario remains negative at −$332; neither figure prices the seven missing exits.

On the $2,000 one-minute replay: $1,410 available cash, $403 unpriced exit debit, $1,813 book equity at cost. The core comparison has $2,387 cash and $237 unpriced debit. These are separate replays, not additive balances; fees, settlement restrictions, fill size, and active option mark-to-market are not modeled.

On the $500 lotto replay with $100 daily debit cap: 78 funded trades, first-bid gross ending cash $805 (2×) / $916 (5×). Chronological gross drawdowns become $186 / $333. With $1 per contract: +$227 / +$338 P/L; exact-target caps plus that cost reduce them to −$98 / +$216. Quote gaps, hindsight-selected rule performance, and concentration in a few wins still prevent a profitability claim. Historical last-saved-bid exits are observations, not verified end-of-session executions.

## Deployment boundary

Run migrations through `0013_option_observations` before starting the new backend. The normal container entrypoint runs migrations. Preserve the database backup and paper-only configuration. No broker credentials, provider selection, scanner schedule, Colima settings, or production deployment are changed by this patch. New experimental results require new market sessions; an empty research panel immediately after deployment is expected.
