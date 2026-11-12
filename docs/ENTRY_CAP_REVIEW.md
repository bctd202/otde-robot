# Passive entry-price-cap review

This feature collects evidence to decide whether the main account's entry limit
deserves a future change. It does not raise a cap, fund an account, create trades,
change selection/exits, rewrite history or add live execution. The existing main
all-in cap, lotto premium ceiling, debit-spread package cap and frozen retest
accounts remain separate and unchanged.

## Prospective entry evidence

Only the ten-position main writer's actual price-limit rejection creates an ENTRY
audit event. All existing entry checks and the original later-quote execution
procedure run first. The event saves the exact verified quote, source/receipt
times, original decision time, frozen policy/costs, premium-plus-entry costs,
closing-fee reserve, available cash and held-slot count. No entry is booked.

A skip is price-only only if it would also fit settled cash and slots at that
moment. A rejection that also lacks buying power is logged but excluded from the
price-only comparison. The scenarios use $125 and $150 **all-in** ceilings as
filters; neither is an application setting. Quotes above both ceilings are marked
not eligible rather than counted as missing exits.

The audit table is append-only, unique by position/event kind, with no cash fields.
It creates no new account or research-funding identity. Existing SKIP events and
positions retain their original meaning. Optional failures use savepoints and
cannot undo the original main-account rejection.

## Exit evidence

Follow the same signal's unchanged completed underlying stop/target/timed exit.
Observe the actual decision clock, then require a quote at least one second later
with independent source/receipt freshness and the exact original contract. A new
decision must be observed within the original 180-second event window; its saved
later-quote request has the frozen 180-second deadline. Same-decision quotes are
not hypothetical fills. Missing candles, session end, missed decisions or expired
quote windows remain unpriced and cannot be repaired by a later favorable quote.

Exit quotes come only from the existing provider cache. The observer makes zero
market-data requests or subscriptions, processes at most 40 receipts per call,
and runs after main account work. No request reserves or baseline scan order change.
Coverage can therefore be incomplete; evidence quality must be checked before a
cap decision. Unknown examples are never assumed sold or worthless.

Signed opportunity arithmetic imports the existing cost helpers without changing
them. Example: $1.00 ask becomes $102.50 entry debit plus $0.50 closing reserve.
A later $0.34 bid yields $32.50 net proceeds under the frozen costs, so the modeled
opportunity result is -$70.00. None of those amounts enter an account ledger.

## Read-only report

`GET /api/entry-cap-review?page=1` and the collapsed Research panel show outcomes
for independent opportunities, with priced-subset averages, positive/negative/flat
counts, open cases, missing evidence and a 20-row paginated receipt log. Bars count
outcomes; they are not money-growth graphs or portfolio returns. Reads never
collect quotes, advance outcomes, initialize accounts or change limits.

Each candidate opportunity uses actual cash/slots at rejection. Extra hypothetical
trades do **not** compete with each other or subsequent real trades for capital.
Consequently even complete quote coverage cannot establish a higher-cap account
return, compounded result, drawdown, or expected edge. No portfolio P/L or return
percentage is manufactured by adding these examples. Larger caps can admit extra
losers; this report is an exploratory input to a later decision, not an optimizer.

Aggregate queries use the latest 5,000 receipts and disclose truncation; all older
audit evidence remains stored. Historical price skips without a rejection receipt
are separately counted and never reconstructed from a later sampled quote. The
November 11 pre-installation inventory found 13 such main-account skips. That is
not a count of profitable missed trades and is not imported as prospective data.

Migration `0020_entry_cap_review` creates one empty audit table only. No activation
or settings change is required. Validate with a verified off-machine backup and
restored-copy migration, preserve existing policies/ledgers/source fingerprint,
deploy after hours, then verify reads, legacy counts and unchanged active limits.
First-session quote coverage can only be checked after prospective collection runs.

The separate `multileg_math.py` foundation in this release remains unwired to any
trading or account code; it does not introduce additional strategies or an IV gate.
