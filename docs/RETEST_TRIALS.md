# Prospective breakout/retest comparison v1

Status: **implemented locally for review; NOT pushed, deployed or activated**.
Initial timing component: `23f354b`. Separately versioned session policy: `5db0602`.
User approved completing the account wiring and resolving shared selection and
early-close policy after market close on October 27, 2026.

## What runs, and what never runs automatically

New identity `breakout-retest-v1` is dormant without its `retest_runs` row. Scans,
startup, migration and API GETs never create that row or fund anything. No live
broker orders are implemented. Explicit operator activation is a separate approval.

Migration `0018_retest_research` only adds six isolated research tables. It imports
no marks/trades and modifies no old rows. Existing main, lotto and legacy accounts,
R calculations, universe, rankings, scoring, stops and targets are unchanged.
The old main account retains its old session policy. New research accounts use
the separately versioned session baseline below, identically in both arms.

## Four separate cash simulations, not one combined portfolio

| Arm | Scenario | Initial cash | Entry timing |
|---|---|---:|---|
| Control | Existing costs | $2,000 | Immediate request at baseline-qualified BUY |
| Treatment | Existing costs | $2,000 | First valid retest for one-minute only |
| Control | 3¢/side stress | $2,000 | Same immediate procedure, stress cash admission |
| Treatment | 3¢/side stress | $2,000 | Same retest procedure, stress cash admission |

Stress replaces existing $0.01/share/per-side slippage with $0.03/share/per-side.
It does not simply subtract $4 from the same closed trade list: each stress account
uses its own settled funds, reserves, entries/skips, settlements and occupied slots.
All four share the same actual observed inputs/quotes, never a retroactive replay.
Never sum their dollars or display them as a single funded portfolio.

Policies are copied from the existing corrected main cash account at activation.
The reviewed policy is one contract, three **held** slots, a $100 all-in entry budget
including the closing reserve; opening commission $1, per-side fee allowance $0.50,
zero closing commission, baseline $1/contract slippage each side. Pending requests
do NOT reserve a held slot (this matches existing main-account admission). Admission
is rechecked in stable order at fill time; OPEN, EXIT_PENDING and UNPRICED exposure
occupies slots. This differs from lotto v3, whose five occupied slots and $100 premium
cap are unchanged. There is no new main-account daily spending cap.

There is no use of unsettled proceeds, automatic replenishment or restart funding.
Closing fees for every held/unknown position are reserved before another entry.
Settlements reuse the conservative next-bank-and-exchange-day 09:30 policy.
Missing exits stay UNPRICED, retain their debit and consume a held slot indefinitely.
There is no guessed expiry payout, zeroing, reset, forced replacement or later recovery fill.

## Selection and opportunity evidence

Preserve scanner candidate ordering (one-minute, then Structured Intraday) and the
first baseline-qualified BUY per ticker/day across engines for account admission.
Both arms receive the same selected opportunity and exact contract. A first
one-minute opportunity can still be logged when Structured already owns that ticker:
account copies get SHARED_TICKER_DAY_SELECTION; the uncapped opportunity record remains.
No second setup, replacement contract or later winner substitutes for a failed first one.

The separate `opportunity` projections have **no account key or cash ledger**. They
apply the same timing/quote evidence but ignore capital/slot limits, showing potential
observations instead of pretending they were funded trades. They also keep observing
the frozen underlying path after cancellation/skip, so a missed target can be reported.
Those path labels are not captured option returns; option-dollar results require
actual qualifying later-quote entry AND exit observations. Lottery hindsight peaks
and historic underlying R retain their original labels and are not imported here.

## Frozen one-minute treatment

At discovery, freeze B/S/T as used in the baseline plan, direction, exact option
identity, premium band/no-chase ceiling, exact pre-rounding **target-planning risk**,
completed supporting bars, strategy version, configuration, source fingerprint,
session policy and decision time. The scanner's optional evidence capture does
not change its candidate outputs; evidence is persisted only in the new opportunity.

1. Only the next five completed one-minute candles count; breakout cannot retest itself.
2. CALL: low <= B <= high AND close > B. PUT: low <= B <= high AND close < B.
3. Frozen stop/target touches cancel, including when a retest appears in the same bar.
4. First qualifying retest requires exact original contract, current eligibility,
   original premium band, no-chase ceiling and extension <=1.35 using frozen planning risk.
5. Request at the actual observation time. Require bid/ask and real receipt at least
   one second later, no more than 120 seconds after request, and <=60 seconds old.
   Reused, stale, future, pre-decision or unverifiable quotes never become fills.
6. Check every newly completed bar for invalidation BEFORE a pending entry in that scan.
7. Missing/conflicting/invalid required bars, expiry, failed verification, cash/slot
   failure, deadline or cutoff cancel permanently. Late-discovered historical retests
   are not backdated. The fifth-bar retest may finish its normal pending quote window.
8. After entry use frozen underlying stops/targets and the common timed-exit policy.
   No premium stop is introduced. Structured Intraday uses immediate requests in
   BOTH arms, with unchanged signal/contract/stop/target rules and shared cash competition.

Cash simulation is ask + slippage + opening costs; exit is max(0, bid - slippage)
less closing costs. Quotes must match contract identity and actual provider/receipt
provenance. A verified zero bid is evidence, unlike a missing quote.

## Separately versioned session/chronology baseline

`session-close-minus15-v1` is used only by the NEW accounts in both arms:

- Stop admitting entries at exchange close minus 15 minutes: 15:45 normal day,
  12:45 on configured 13:00 early closes. This is an explicit new entry cutoff;
  the old scanner itself had no standalone 15:45 entry admission rule.
- Timed exit is the completed candle starting at that cutoff (observed after
  15:46 or 12:46), followed by the normal later-quote exit request and 180-second deadline.
- Stop takes precedence over target when both touch. No exit is inferred from an
  unavailable candle. A touch during the minute containing the actual entry quote
  has ambiguous before/after chronology and becomes UNKNOWN, not an awarded winner.
- An exit first discovered more than 180 seconds after its completed bar is unknown.
  Deadline/close failures are unknown exposure, never a fabricated liquidation.
- Unknown calendar years and closed exchange dates fail closed. No changes to the
  legacy performance evaluator or historical 15:45 results are made.

Thus this is a prospective comparison against a **versioned immediate-entry
baseline**, not a claim that the old account's exact fill list will be reproduced.
The only difference BETWEEN the new arms is one-minute retest entry timing and its
specified invalidation/reverification; common session and accounting policies match.

## Collection and restart safety

Baseline scanning, lotto and main-account work finish first. Optional research
uses shared cached inputs; exact held/pending chains may be refreshed afterward,
at most two per pass, held first, shared across projections. Every underlying
Tastytrade HTTP request in that optional context enforces the original reserve;
unknown budget or unsupported reserve handling means no extra request. No weakened
freshness, new universe, or overlapping scanner thread is introduced. Bounded
requests still take time: measure the new `retest_research` phase and coverage in
the actual forward run; do not claim throughput is solved from unit tests.

SQLite writer lock + caller transaction/savepoint protect positions and append-only
cash/decision/quote events together. Dedupe keys prevent duplicate funding, entry,
exit, settlement and minute observations. A research error rolls back its savepoint
without rolling back successful baseline scans. Runtime errors are logged; scan
collection failures also append an error event when the DB remains writable.
On a regular-session restart, wait for real scan inputs instead of treating an
empty startup cache as proof that candles are missing. Old expired holdings remain
unknown; there is no post-outage backfill.

Source/configuration drift disables new research admissions and marks evaluation
inconclusive. Do not patch an activated trial in place to improve outcomes; review
a new identity instead. Scanning never changes existing run policy or spec hash.

## Frozen 60-session evaluation

Activation is allowed outside regular hours only. Freeze exactly 60 consecutive
exchange sessions from the actual boundary, including outages and zero-trade days.
No outcome-dependent tuning or extension. Freeze revision, source/configuration
fingerprint, inherited costs/caps and calendar in one transaction with the four
funding events. Repeating activation returns the existing run, never resets it.

All of the following are required, separately for baseline and stress cash scenarios:

- >=100 distinct first one-minute baseline opportunities; >=30 completed one-minute
  treatment trades. Structured trades affect account results, not this sample minimum.
- >=95% required input coverage. Report the MINIMUM of (a) scheduled minute x frozen
  base-universe candle coverage, including outages, (b) first-opportunity planning
  evidence coverage, and (c) required retest-decision quote-input coverage. A good
  candle feed cannot conceal missing retest quotes. Flex candidates remain selectable;
  their individual decision evidence is included, but the scheduled grid covers the
  frozen base universe, not reconstructed historical flex membership.
- >=90% post-decision entry quote coverage and >=90% exit quote coverage, separately;
  corresponding arm differences <=5 percentage points. Denominators are ALL requests,
  not only filled/closed trades; overdue/unknown exits remain exit requirements.
- Positive treatment net P/L and treatment-minus-control advantage under both costs.
- Complete liquidation-equity maximum drawdown <=$200 and no worse than control.
- Positive treatment P/L after removing its three best sessions; positive advantage
  after removing its three largest contributing sessions. Chronological ties are
  equivalent dollar deletions; no choosing favorable removals.
- No complete performance claim with unresolved holdings or valuation gaps. To call
  a daily path complete, require every scheduled minute plus an end-of-day observation
  within three minutes of the close. Missing samples invalidate full drawdown claims;
  the observed drawdown is only a lower bound. This intentionally can be stricter
  than the 95% input-coverage gate. No imputation of an outage as a zero-return day.

Uncertainty: same aligned 60 daily liquidation-equity changes, 56 overlapping
noncircular five-session blocks, twelve paired blocks per resample, 10,000 replicates,
seed 20261027; interpolated percentile 95% interval of total treatment-minus-control
dollars. Same indices in both arms, no independent-trade bootstrap, no dropped days.
Unknown valuations => INCONCLUSIVE. Report the interval alongside the gates; PASS
means these preregistered paper criteria were met, not proven future profitability.

## UI and read-only evidence

Research page: Breakout vs. retest, explicit inactive/collecting/window-ended state,
separate account selector, observed equity graph with gaps, input/entry/exit coverage,
unresolved count, verdict and paginated account/opportunity decisions. No activation
button. `/api/retest-research?page=1&view=accounts` (or `opportunities`) is read-only.
All underlying events and frozen plans remain in the isolated SQLite tables for audit.

Reports stream historical observations instead of loading all quote JSON at once.
Working scans only load active projections and unfinished opportunity paths; retired
unknown outcomes are not repeatedly materialized as the trial grows.

## After-hours deployment and activation checklist — NOT executed

1. Review this protocol and the complete diff. Run backend tests/lint/types, frontend
   tests/lint/types/build and migration tests. Inspect synthetic UI separately from real data.
2. With explicit push/merge/deploy approval, wait for CI green. Record deployed revision,
   preserve `.env`/override, hold new scans and allow in-flight work to finish. Take a
   verified online SQLite backup; copy/hash it on main Mac; retain old container images.
3. Deploy and apply additive migration 0018. Verify old accounts/rows unchanged,
   paper-only health, read-only endpoint NOT_ACTIVATED, and zero research funding/events.
   Migration or deployment must not activate the comparison.
4. Obtain separate approval for the prospective start. Outside regular hours, in the
   backend container with the reviewed deployed code, invoke the operator service:

   `python -m app.services.retest_trials activate --revision REVIEWED_FULL_SHA --confirm ACTIVATE-PAIRED-PAPER-RESEARCH`

   `REVIEWED_FULL_SHA` is a placeholder, not a paste-ready deployment command. The
   service uses the actual UTC clock, not a supplied backdated start. Inspect existing
   main policy before activation; any mismatch needs review, not a forced reset.
5. Verify one run, four account identities, exactly four $2,000 funding events,
   zero imported trades, frozen source/spec hash, expected 60 sessions and matched
   constraints. Record activation separately from code deployment; resume intended scan state.
6. Next session inspect both-arm discovery, later quote evidence, stress admission,
   Structured participation, cash/reserves, timing, and denominators. Never change
   thresholds to make a bad day look better. Unknowns remain visible.
7. After activation do NOT revert the DB or delete accounts to roll back code.
   Preserve all new evidence, review how open exposure will be managed, and only
   then approve a rollback. Schema downgrade intentionally refuses to erase research.

## Data limitations

No broker order/fill reports, independent bid/ask-side timestamps, guaranteed queue
position, size or partial fills. Shared provider `updated-at` and real application
receipt are distinguished. These are conservative paper estimates, not live money.
Missing data can make a long run inconclusive; the implementation never fixes that
by inventing receipts, exits, zero returns or an extra collection period.

## Local validation — October 27, 2026

- Backend: 373 tests passed; Ruff and mypy passed (41 application source files).
  Two existing dependency deprecation warnings remain.
- Frontend: 93 tests passed; ESLint, TypeScript and production build passed.
- Additive migration and historical-row preservation tested on local SQLite only.
- Verified early-close timed exits, later quotes, scan-savepoint error isolation,
  restart/idempotency, settlement/reserves, and the 60-session evaluation gates.
  Structured fills cannot satisfy the 30 one-minute treatment-trade minimum.
- Browser review at 1024×1366 and 390×844: inactive state, separate account selector,
  unknown graph gaps, opportunity warning, pagination and dark-theme readability.
  Active screenshots use explicitly labeled synthetic fixtures, not forward results.
- Local migrated preview remained NOT_ACTIVATED with zero run/account/event rows
  after UI reads. No production migration, settings change, push or activation.
