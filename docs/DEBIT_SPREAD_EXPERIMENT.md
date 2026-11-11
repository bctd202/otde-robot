# Isolated debit-vertical paper account — review build

Status: implemented locally for review. DEBIT_SPREAD_ENABLED=false by default.
No deployment, production migration, funding, settings change or activation is part
of this task. No broker order path exists. Existing main/lotto/retest accounts,
strategy logic, R and histories are unchanged.

## Frozen initial policy

- Account identity debit-vertical-v1; independent $2,000 simulated cash.
- Bull-call and bear-put debit verticals consume existing ONE_MIN_0DTE and
  STRUCTURED_INTRADAY BUY entry evidence. Baseline comparator is the active
  tasty-capacity-ten-v1, not the earlier three-position account.
- One contract per leg; multiplier 100; same ticker/right/exact expiration as the
  original long. No 5–45 DTE gate or 21-DTE management rule from the broader draft.
- $250 all-in per package: net entry cash debit plus both closing-fee reserves.
  It is not a per-leg ceiling. Ten positions including pending entries and
  unresolved exposure; no separate daily spending cap. Ten slots are the proposed
  initial review default, not a change to any current account.
- No borrowing or unsettled-proceeds recycling to fund entries. Negative actual
  modeled liquidation outflows remain signed cash liabilities and block subsequent
  unaffordable entries. Missing short-leg liability blocks new admissions in THIS
  account until reviewed; existing experiments remain independent.
- Per leg: $1 opening commission, $0 closing commission, $0.50 fee allowance each
  side and $0.01/share slippage each side. Existing cost helpers are imported intact.

## Prospective activation and evidence

Only an explicit after-hours activate(db, revision=full_reviewed_sha, now=actual_utc)
call inside a caller-owned transaction can fund this account. The feature must
also be enabled, paper-only and configured for Tastytrade. This task never calls it
against production. Flag changes, GET, startup and scans cannot fund an account.
Activation saves costs, settings, code fingerprint and exact revision; initial
watermark excludes all existing entry marks. Repeating activation preserves policy,
funding, balances and start date. Partial activation requires review.

At most 40 new entry marks are consumed per scan. First recorded ticker/day wins
across both existing engines; invalid, missing-evidence and capacity skips retain
that place so later winners cannot replace them. Record every consumed prospective
qualifying opportunity separately from funded entries. Old marks, manual origins,
wrong providers/versions and out-of-session decisions cannot create fills.

## Strikes and exact identity

Long is the original selected exact contract. For CALL, select the lowest listed
call strike >= frozen target and > long strike. For PUT, select the highest listed
put strike <= target and < long strike. Option-symbol ordering breaks ties.

The formal inequalities are authoritative: if target equals the long strike, a
valid next outward listed strike is allowed. The earlier draft's assertion that
this necessarily means no hedge exists was incorrect. No arbitrary fallback,
replacement expiry, later contract reselection or naked-long substitution.

Selection reads the already-populated Tastytrade instrument cache only (six-hour
maximum age). Save that snapshot, cache time and digest with the immutable decision
so selection is reproducible. Full listings stay in decision events; compact
position projections and paginated UI payloads do not reload that audit archive. Nearest-listed means nearest within that recorded
listing snapshot, not a guarantee that no exchange added a strike afterward. Quote rows alone cannot prove the nearest listed strike, because a
missing quote could hide a nearer instrument. No instrument-cache proof means a
skip. Freeze the selected hedge even if its quote is absent; await that identity's
entry quote until the deadline, never substitute a farther strike. Cache adapter
fails closed if metadata is stale/malformed or the provider layout changes.

## Paired execution and cash

Same scanner observation does not establish freshness. For EACH leg verify OCC
identity, original expiry/strike/right, explicit Tastytrade/live provenance, actual
REST receipt evidence, non-future bid/ask and receipt clocks within 60 seconds,
and post-decision timing. All six source/receipt timestamps must span <=2 seconds.
Entry additionally needs positive bids and <=20% (ask-bid)/ask spread per leg,
consistent with the current main account's entry convention.

A pair enters only with quotes >=decision+1 second, within 120 seconds of both its
request and original baseline entry evidence. Both pass together or no package
fill/debit occurs. Missing entry stays pending then becomes SKIPPED; it is never
an entered UNPRICED position. This all-or-none package is a PAPER assumption, not
proof of executable combo liquidity, quote size, partial fills or brokerage fills.

Using the unchanged cost helpers with explicit policy and multiplier 100:

    entry_debit = entry_premium_cents(long_ask, cost, 100)
                  - exit_premium_cents(short_bid, cost, 100)
                  + 2 * cost.opening_cost_cents
    exit_credit = exit_premium_cents(long_bid, cost, 100)
                  - entry_premium_cents(short_ask, cost, 100)
                  - 2 * cost.closing_cost_cents
    net_pnl = exit_credit - entry_debit

Buy long at ask+slippage, sell short at bid-slippage. Reverse those sides on close.
Reject nonpositive premium debits or debits >= spread width. Fees/reserves count
toward the entry ceiling; don't round over-limit quotes down. Positive proceeds
remain unsettled until the existing next bank/market day 09:30 calendar permits
release. A negative exit_credit is charged to settled cash immediately, not
floored to zero. Initial debit is NOT the only possible cash obligation when
modeled execution and assignment are incomplete.

Example: long ask .45 / short bid .10 yields $40 debit and $1 closing-fee reserve.
Long bid .75 / short ask .20 later yields $52 net proceeds: $12 realized P/L.
Long bid 0 / short ask 3 yields a signed -$302 close outflow, not a $0 sale.

## Exits and unknowns

Original SignalPerformance stop/target/timed outcome requests liquidation using
result_model.exit_completed_at; no new exits or premium stops. Frozen stop/target
are audit data; no rolling recomputation. A completed event cannot predate entry.
The first observed valid event requests exit; both later quotes must arrive after
request+1 second within 180 seconds, with the same identity/freshness/alignment
checks. Underlying data gaps, missing event clocks or already missed event windows
remain unknown. A later favorable quote cannot repair an expired exit deadline.

OPEN, EXIT_PENDING and unresolved positions consume slots and closing reserves.
Source quotes age independently of reads; old cached values cannot look current.
Unpriced positions make total equity incomplete. A new entry with valid paired
quotes is skipped if any held package lacks a current paired valuation; this
conservative liability guard applies only to the new account. Contract expiry without exit or
settlement evidence becomes EXPIRED_UNRESOLVED, not a zero-dollar expiry, sale,
exercise or proven assignment. No share ledger exists. ASSIGNED_UNMODELLED is a
reserved unresolved status, not automatically asserted from a stock price.

Theoretical expiry width/debit/max profit/loss and breakeven are labeled scenarios,
not cash returns or guaranteed execution/assignment bounds. No theoretical payoff
is substituted for a missing bid/ask or used to close a financial position.

## Isolation and comparison

New account/position/event/snapshot tables are additive migration 0019_debit_spread.
Existing protected source hash must stay exactly
4fe8e0a500a9d2440e6e0de0bb93bcd46f7c006abf78710618298318ec14cc57.
No maintenance acknowledgment or new identity for the existing retest study is
needed or permitted by this task. Existing cost/strategy/provider helpers are
imported without modification. Baseline scanner ordering remains intact.

Optional processing comes after existing main/retest/lotto work, in its own
savepoint, including after-hours reconciliation. Disabled mode does not run the
new hook. Collection is CACHE ONLY: zero added provider requests, no subscription
changes, no consumption of scanner request reserves. Current caches can omit exit
quotes; this version does not promise a high fill rate. Additional collection
requires a separately reviewed bounded plan before activation if coverage proves
insufficient. Optional exceptions cannot roll back successful baseline work.

ALL plots each day's final saved valuation; 1D plots the latest recorded day and
breaks missing-minute/unknown-price intervals. Daily endpoints are not an intraday
drawdown claim.

The read-only Research view has its own account-value/return graph and paginated
trades/opportunity log. No existing account default or graph calculation changes.
Unactivated display says planned cash, not a funded $2,000 balance.

A matched entry requires actual ENTRY ledger evidence in BOTH this account and
named main account for the same signal_id after spread activation. A valid selected
spread alone is not a fill. Unresolved matched entries stay in the denominator;
show known closed-pair P/L as a subset, unresolved counts and separate entry/exit
coverage. Each account's own full cash results remain separate from the matched
comparison. No lifetime-return comparison implying equal start dates; no sum of
trade percentages or separate accounts. Skips remain in the opportunity log.

## Review and deployment handoff

1. Review this specification, the ten-slot default, quote coverage and conservative
   unknown-short-liability admission block. Run backend/frontend required checks
   and unchanged-fingerprint/legacy-preservation tests.
2. After a separate deployment instruction, take a verified off-machine backup,
   deploy disabled after hours and apply ONLY the additive migration. Verify no
   spread accounts/events/funding exist and existing retest stays unblocked.
3. After separate activation approval, verify exact reviewed revision/provider,
   enable feature and call explicit activate in one transaction after hours.
   Confirm one $2,000 FUNDING event and the saved prospective watermark.
4. Next regular session: verify paired later quotes, skips, signed close flows,
   timing/request isolation and preserved old accounts. Do not assume profitability
   or activate a batch of additional strategies. No production action occurred in
   this implementation task.
