# Lotto forward experiments and money-first dashboard

This is prospective paper research, not broker execution or evidence that an exit
rule is profitable. Previous lottery observations and replay outcomes are preserved.
No old peaks are credited to the new accounts. Main-engine selection, stops,
targets, and historical R calculations are not changed by this experiment.

## Main view: two shared-direction exit-rule accounts

The default view now compares two independent $500 paper accounts. Both accept
CALL and PUT candidates, sharing the same cash, one pending/open/unpriced slot,
$100 daily all-in debit cap, and one accepted contract per ticker/day across both
directions. The two accounts are alternatives, never summed into a portfolio:

| Exit rule | Account key |
| --- | --- |
| 5× trigger | `lotto-v2-20261026-both-fixed5` |
| 40% trail after 2× | `lotto-v2-20261026-both-trail40` |

They initialize once on the first processing call on or after October 26, 2026,
09:30 Eastern. Late deployment activates at the actual processing time; discoveries
before activation are excluded. GET requests cannot create or fund an account.
There is no import, transfer, or reset of earlier balances, trades, or quote paths.
These account identities and frozen policies survive restarts unchanged.

Each exit-rule account makes its own entry decisions. An open or unpriced position
in one rule does not block the other rule, so entries may diverge as exits and
available settled cash diverge. This compares complete cash-constrained strategies,
not a perfectly paired exit-only experiment. Within each account, earlier discovery
waves precede later waves; within a wave rank by score descending, spread ascending,
then option symbol ascending, with no preference for calls or puts. The existing
direction-specific input evidence must match the candidate's actual option right.

The balance graph is the selected account's return after modeled costs, not a sum
of trade percentages. Calls and puts show full-account counts and closed-trade net
P/L below the graph, independent of trade pagination. Open and unpriced outcomes
are shown separately and excluded from realized P/L, not assigned zero losses.
The two direction totals are contributions, not two funded balances.

Costs, later-quote entry/exit fills, target/trail thresholds, settlement, end-of-day
handling, quote guards and main-engine logic remain unchanged. New account rows
reuse the existing trial tables; no schema migration or historical rewrite is needed.

## Original four directional comparisons (preserved)

Each receives $500 simulated cash once, starting at the first processing call on
or after October 19, 2026, 09:30 Eastern. Late deployment means late activation;
there is no backfill. Permanent identities:

| Direction | Exit variant | Account key |
| --- | --- | --- |
| CALL baseline | 5× trigger | `lotto-v1-20261019-call-fixed5` |
| CALL baseline | 40% trail after 2× | `lotto-v1-20261019-call-trail40` |
| PUT experiment | 5× trigger | `lotto-v1-20261019-put-fixed5` |
| PUT experiment | 40% trail after 2× | `lotto-v1-20261019-put-trail40` |

These are alternative experiments, **not four sleeves to sum into one portfolio**.
They are also separate from the $2,000 main-engine account and manual positions.
Restarting, changing the selected view, or changing environment settings does not
reset funding, balances, or frozen policies. GET requests never initialize accounts.

## Entry and cash rules

- Live Tastytrade, verified exact contract, same-day expiration, current-session-v2
  inputs, and `lotto-call-session-v2` or `lotto-put-session-v2` evidence required.
- CALL discovery retains its corrected bullish rule: above VWAP and opening-range
  high. The separate PUT experiment requires below VWAP and opening-range low.
  Existing cheap-contract, spread, volume, open-interest and delta filters remain.
- Both exits in a direction accept the **same entries**. Within a discovery wave,
  rank score descending, spread ascending, then option symbol ascending. One
  pending/open/unpriced idea across the paired accounts per direction. At most one
  accepted contract per ticker/day. Neighboring strikes are not independent bets.
- Entry decision must be within 120 seconds of discovery. A restart cannot enter
  an old discovery. Actual entry needs a later observation with bid, ask and local
  receipt timestamps no more than 60 seconds old, all after decision +1 second.
  Entry deadline is 120 seconds after decision. Missing/ineligible entries are
  explicitly skipped, not replaced with hindsight winners.
- One contract; at most $50 all-in per entry including closing-cost reserve;
  $100 all-in daily debit cap. Both paired accounts must have settled cash and
  budget available. Positive bid and spread no wider than 30% at entry.
- Modeled opening costs $1.50, closing costs $0.50; one cent of option premium
  slippage per side ($1 per standard 100-share contract). These are assumptions,
  not verified tastytrade invoices. Cash amounts are integer cents.
- Entry is ask plus slippage. Exit is bid minus slippage, floored at zero, with
  closing costs charged separately. A verified zero bid is evidence; a missing
  bid is unknown. Costs can make the loss exceed the initial debit.
- Sale proceeds are unsettled until the next eligible banking/market day at
  09:30 Eastern. Settlement transfers cash; it never creates profit. Unknown
  calendar years do not release unsettled funds.

## Frozen exit comparison

Thresholds use modeled entry **option premium**, including entry slippage but not
opening fees. The UI's net money-back multiple instead divides net sale proceeds
by the complete entry debit. A 5× trigger does not imply 5× net cash returned.

1. Fixed: first fresh bid at least 5× modeled entry premium requests exit.
2. Trail: first fresh bid at least 2× modeled entry premium arms the trail.
   A later bid at or below 60% of the highest observed bid requests exit.
   There is no pre-arm percentage stop in this variant.

Neither uses its triggering quote as a sale. Both wait for a later verified quote
after the request +1 second, within a 180-second deadline. The later bid determines
the sale even if it has fallen below the target/trail barrier. No perfect peak or
guaranteed target fill. A missing deadline leaves the position UNPRICED permanently;
later favorable prices cannot repair that outcome retroactively.

New entries stop 15 minutes before exchange close. Remaining positions request
exit five minutes before close, including configured early closes. At the close,
unresolved positions retain their debit and become unknown. The existing independent
housekeeping job reconciles these states without overnight feed polling. Unknown
positions block further paired entries; closed winners alone are not full results.

## Evidence and limits

Migration `0016_lotto_trials` adds separate account/position/event tables and nullable
receipt/provider/mode columns to quote snapshots. Legacy quote columns and records
are unchanged; missing provenance is not manufactured for older snapshots.
Funding, decisions, skips, entries, exit requests, exits, gaps, settlement and
account marks are appended as events. Each event has an idempotency key. Reads do
not mutate cash or historical observations. Transactions preserve paired entries.

Runner evidence counts distinct bid timestamps reaching 2× and 5× discovery ask,
time to first observation, lowest observed bid before that observation, and longest
sampled span with no more than 90 seconds between successive qualifying quotes.
Repeated cached bids do not count repeatedly. These are sampled observations,
**not continuous executable liquidity**. Quote size is unavailable. No queue,
partial-fill, exercise, assignment, or guaranteed fill simulation is provided.

The lotto page defaults to the shared 5× account, with the shared trailing account
next in the selector. The original four comparisons remain available in their own
selector group and continue using their original paired directional entry rules.
The selected view shows one account-value graph, then paginated Trades with
cost, proceeds, net dollar outcome and either percentage or money-back multiple.
Open values are estimates; missing values are unknown. The observation archive
groups related strikes within a scanner wave. Historical CALL replay totals stay
CALL-only; PUT is inspectable through forward accounts and quote paths.
The old date selector and research charts remain available off the main view.

The main performance page likewise defaults to account value and simple trades.
R, raw/directional underlying movement, and original research arithmetic remain
under Research. Historical shadow/replay comparisons remain under Option execution.
No trade-return percentages are summed into an account return.

## Deployment boundary

This patch does not deploy itself. Follow the verified, WAL-aware predeployment
archive procedure in `CORRECTED_TRIAL.md`, upgrade through 0016, then check scanner,
feed, paper-only status and all account identities. Do not downgrade these tables
after collecting evidence without first preserving them; prefer a forward repair.
The feature contains no live-order endpoint or automatic provider fallback.

## Shared-account verification — October 24, 2026

The shared-account patch has 247 passing backend tests and 74 passing frontend
tests, plus Ruff, Mypy, ESLint, TypeScript and production frontend build checks.
New cases cover independent exit-rule capacity, shared CALL/PUT cash and daily
caps, cross-direction ticker limits, direction-neutral score selection, PUT input
provenance, unknown exposure, once-only funding, late activation without imported
history, preserved original accounts, full-account directional P/L reconciliation,
selector grouping, page reset and read-only summaries. Unit tests use isolated
databases and synthetic quotes; they do not establish live execution profitability.
The scheduled October 26 start only applies once the code is deployed and the
scanner processes the new accounts; passing local tests does not activate them.

## Original local verification — October 18, 2026

238 backend tests and 73 frontend tests pass. Ruff, Mypy, ESLint, TypeScript and
the production frontend build pass. Backend tests use isolated temporary databases,
including fresh-install and legacy-data migration checks. Coverage includes paired
entries, later-quote fills, fixed/trailing decisions, cash/cost caps, T+1 settlement,
zero versus missing bids, early closes, provider/input gates, PUT isolation, read-only
pagination and quote-path evidence. Synthetic Chrome checks pass at desktop, 390px
and 320px for graphs, gaps, trade units, pagination, independent account selection
and scheduled/unknown states. This is not a live-feed or broker-fill verification.
No production database was archived or changed, and nothing was pushed or deployed.
