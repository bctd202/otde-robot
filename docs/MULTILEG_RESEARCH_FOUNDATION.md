# Multi-leg research arithmetic — next-stage local foundation

This is an isolated math library, not a new signal engine or funded account.
`multileg_math.py` has no callers in the scanner, APIs, account writers or provider.
The deployed debit-vertical account continues using its previously frozen helpers.
No migration, data backfill, account activation or production setting is added here.

## Frozen arithmetic conventions

- Standard 100-share equity options only; one underlying and one common expiry.
  Reject diagonals and adjusted multipliers rather than guess their deliverables.
- Signed integer leg quantities: positive long, negative short. Intrinsic is always
  nonnegative; apply its sign once through quantity.
- Merge identical legs while retaining actual quantities. GCD-normalized shape is
  a separate descriptor with an explicit scale, never the economic position.
- Opening premium is total signed integer cents for the actual package, positive
  for credit, negative for debit. Expiry scenarios exclude fees, execution and
  assignment. Underlying prices and hypothetical USD payoffs use Decimal.
- Analyze all strike breakpoints, the zero-price endpoint and the upper tail.
  Unbounded profit/loss is represented explicitly by `None` on its named field.
  Bounded max loss is a nonnegative magnitude. Flat zero-payoff regions are
  intervals, not a fabricated unique breakeven. No theoretical outcome books cash.
- Model probability integrates every interval of positive signed payoff: outside
  breakevens for long straddles/strangles, inside for short versions. Volatility
  uses fractional annual units, time uses years, rates/yield are explicit. The
  risk-neutral constant-volatility lognormal assumption is a scenario model,
  never observed win rate or a profitability claim. Zero payoff is not positive.
- Signed cash arithmetic imports the unchanged existing cost helpers. Round each
  contract with those helpers, then scale quantity; assess fees on every contract.
  A short buyback is a signed outflow. A zero bid is allowed in arithmetic without
  asserting an executable fill. Quote identity, chronology, freshness, liquidity,
  capital, settlement and assignment remain outside this pure library.

These conventions fix the V2 quantity, probability and rounding defects without
changing historical calculations or adopting the proposed strategy/risk gates.

## Data feasibility verified November 11, 2026

An operator-run, after-hours probe of the existing Tastytrade connection returned
market-metrics objects and IV-rank values for all 20 configured tickers. The probe
used one OAuth refresh and one read-only market-data request, no DB writes, no
orders and no scanner/provider code changes. It was a feasibility observation,
not the start of an IV history archive or proof of regular-session freshness.

The [official snapshot endpoint](https://developer.tastytrade.com/reference/market-metrics/getMarketMetricsIndex/)
includes IV rank, its source, update times and per-expiration volatility information.
The observed rank/index fields use fractional values; the observed 30-day IV field
uses percentage values. A future decoder must validate field-specific units,
timestamps and source. It must not silently compare a fractional rank to a
percentage threshold or substitute the general object update time for the IV time.

Before any IV gate is activated, choose and freeze broker-computed rank versus an
independently calculated ATM-IV history. They are not interchangeable. Current
snapshots cannot fill historical gaps. A fixed 60-observation local warm-up is not
an unavoidable provider limitation, nor a complete 252-session history.

## Next strategy handoff

Credit verticals are the next candidate, not yet implemented or activated. Resolve
the conflicting width/risk rules and define maximum loss/collateral separately
from credit received. The proposed 2% trade risk, 6% total risk, five-slot policy,
2%-of-spot width and 33%-credit gates are not silently adopted by existing tests.

Finish one deterministic directional filter, session decision window, expiry
selection, event/dividend policy and overnight lifecycle. Quote collection must
be bounded and preserve baseline request reserves. Freeze independent evaluation
dates, missing-evidence handling and uncertainty analysis before funding it.

Broker permissions remain distinct from paper capital arithmetic. Tastytrade
documents margin-account requirements for spreads; this foundation does not add
live execution or establish that a real cash account can execute the experiment.
[Account guide](https://tastytrade.com/learn/accounts/account-resources/margin-vs-cash-accounts/).

Validation covers independent payoff vectors, duplicate/quantity preservation,
unbounded tails, flat zero regions, invalid identities, long/short probability,
deterministic boundary cases, signed cash and per-contract rounding.
