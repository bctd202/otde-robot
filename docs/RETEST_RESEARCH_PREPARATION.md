# Breakout/retest initial preparation record — superseded

**Historical preparation notes below.** The account wiring was subsequently
approved and implemented locally. See [the current frozen protocol, validation
and rollout plan](RETEST_TRIALS.md). No production deployment or activation has
occurred. Statements below about unimplemented wiring describe the earlier commit.

Prepared October 27, 2026 against `c8ec116`, matching the read-only inspected
Parlay-Mac checkout. Its tracked working tree was clean; operator overrides,
environment backup and exports were untracked and were not read or changed.
Production health returned OK/paper-only. No production writes were made.

## Exact status

This is a tested, **inert entry-timing component and evaluation-method proposal**,
not the complete requested two-account experiment. Nothing imports it into the
scanner, API, scheduler, accounts or startup. There is no activation function,
new account, migration, environment flag, automatic deployment or live order.
Do not merge/deploy it expecting a new trial to run.

Implemented:

- Immutable, versioned setup and decision evidence, serializable for restart handoff.
- Five completed-bar retest gate; strict call/put close condition; no breakout-bar self-retest.
- Stop/target cancellation before retest and before any pending entry eligibility.
- Missing/conflicting/invalid required bars fail closed. A retest first observed
  after its decision minute is rejected, not retrospectively assigned a request time.
- Same-contract verification, original premium band/no-chase ceiling, exact frozen
  planning-risk extension, and current contract liquidity verification.
- Fresh bid/ask and actual receipt checks; at least one-second later evidence,
  120-second entry deadline, capacity cancellation, explicit session cutoff.
- Idempotent repeated/backward observations and JSON state round-trip.
- Deterministic calendar enumeration and paired five-session block bootstrap.
- Updated documentation distinguishing current cash accounts from historic R/shadow views.

**Not implemented:** durable opportunity/ticker-day admission, two new accounts,
funding/activation/watermarks, cash and settlement projections, account-level
idempotency/locking, Structured Intraday mirroring, held-position exits, quote
collection/reserve integration, the stress-account path, UI/API, automated final
verdict or a completed deployed-session coverage study. ENTRY_ELIGIBLE is NOT
a fill: a future adapter must atomically recheck capital/reserves and record it.
Serialization tests are not database crash/recovery tests.

## Material findings to resolve before integration

1. **Opportunity selection versus account admission.** `performance._record_option_entry`
   deduplicates by date/ticker across BOTH strategies; one-minute candidates are
   processed before Structured Intraday in the scan. `forward_account` consumes
   those shared entry marks. Simply creating one-minute accounts from every BUY
   would not reproduce this control. Recommended: separate a first-one-minute-BUY
   opportunity ledger from shared-account admission. Log all first opportunities;
   record baseline selection and capacity skips explicitly; let both accounts keep
   identical cross-engine ticker and concurrency rules. Do not import historical
   marks or treat a skipped opportunity as an account fill. Review this mapping
   before implementing the control/treatment adapter.
2. **Cutoffs and early closes.** The baseline underlying outcome evaluator uses a
   fixed 15:45 candle cutoff; cash-account guards separately check the real exchange
   close. `rank_parlays` does not define a standalone 15:45 entry cutoff. A guessed
   12:45 early-close exit or new earlier entry deadline would change more than entry
   timing. The component deliberately requires explicit entry/timed-exit cutoffs
   and rejects impossible early-close chronology. Review either faithful baseline
   handling (including unknown exposure when no valid exit exists) or a separately
   versioned baseline correction BEFORE freezing/activating this experiment.
3. **Planning-risk evidence.** Production uses `max(abs(trigger-stop), price*.002)`
   for target planning and extension, then rounds displayed B/S/T. The old snapshots
   do not persist the exact planning-risk distance or the complete supporting bars.
   Do not reconstruct it from rounded targets or actual fill-to-stop distance.
   Add prospective evidence-only capture at decision time in the future adapter;
   compare baseline outputs to prove selection did not change. The component
   accepts exact risk/evidence from that adapter, never recomputes a rolling B.
4. **Capacity is not an entry-timing parameter.** Current main account: $2,000,
   three held slots, $100 all-in entry budget INCLUDING closing reserve. Lotto v3:
   independent $500 accounts, five occupied slots and $100 CONTRACT PREMIUM cap,
   no daily spending cap. The lotto approval did not change the main account.
   Keep control/treatment capacity identical and frozen; use uncapped opportunity
   observations to increase research visibility without pretending capital is unlimited.
5. **Broker evidence cannot be invented.** Tastytrade's shared updated-at is not
   independent bid/ask event timestamps. This component uses the current conservative
   quote policy without claiming queue/size/partial-fill guarantees. These require
   new evidence or a separate explicit simulation model, not a fake filled-order log.

No baseline strategy, selection, account policy, record, R calculation, lotto rule,
stop or target was modified to resolve these issues in this preparation.

## Proposed frozen experiment contract (approval/integration still required)

- Separate versioned control/treatment identities, $2,000 each, one-time actual
  prospective activation. Frozen source revision, configuration hash, full policy
  and activation watermarks. No funding on GET/startup, no backfill, resets,
  imported positions or relabeling old accounts. Preserve old accounts/history.
- Control follows unchanged immediate-entry procedure. Treatment changes ONLY
  one-minute entry timing. Structured Intraday remains identical in both, with
  shared intra-account capital competition. Different fills can naturally create
  later capacity differences; record them instead of forcing matching balances.
- At the first baseline-qualified one-minute BUY per ticker/day freeze direction,
  B/S/T, exact planning risk and completed-bar evidence, original exact contract,
  premium band, no-chase ceiling, versions/configuration. No replacement or second setup.
- Next five completed candles only. Call: low <= B <= high and close > B; put:
  low <= B <= high and close < B. Stop or target touch wins in the same candle.
- First retest requires current eligibility, premium band/no-chase, extension
  <=1.35. Entry must use later bid/ask/receipt evidence, >=1 second after the actual
  request and within 120 seconds, under existing freshness policy. Check completed
  bar invalidation FIRST in every pending-entry scan. Missing bars, expiry,
  verification failure, capacity failure, quote deadline or cutoff cancel.
- Preserve frozen underlying stops/targets and the reviewed baseline timed exit;
  no new premium stop. Ask-plus-slippage entry, bid-minus-slippage exit, closing
  reserves, settled cash and concurrency are identical in both arms. Pending and
  unknown exposure treatment must be explicit and identical, with unresolved
  holdings continuing to consume capital/slots. Missing exit never becomes $0 loss.
- Record opportunity results independently of account cash results, including
  cancellations, missed runners and capacity skips. A hindsight target hit/lotto
  peak is not an executable outcome. Keep existing evidence labels.
- Durable append-only decision/quote/skip/cancel events, transactional state
  projection and unique dedupe keys. Read-only reports never advance a trial.
- Collect exact pending/held contract quotes after baseline feed work, obeying the
  existing baseline reserve and bounded refresh budget. No broad new polling,
  replacement symbols or weakened freshness. Validate fairness/coverage between arms.

## Frozen evaluation proposal

Count **60 consecutive exchange sessions from actual activation**, including
outages and true zero-trade sessions. Activation during a session counts that
partial session; after close begins at next exchange session. Prefer reviewed
pre-open activation. No result-driven extension or tuning. Unsupported calendar
years block activation. Insufficient evidence means INCONCLUSIVE, not pass/fail.

Require all of:

1. >=100 distinct baseline one-minute opportunities and >=30 completed treatment trades.
2. >=95% required input coverage; >=90% post-decision entry quote coverage and
   >=90% post-decision exit quote coverage separately; corresponding arm differences
   <=5 percentage points. Freeze denominators before activation: expected scheduled
   inputs, entry requests, exit requests—not only successfully filled trades.
   Do not count missing data as a no-trade success; distinguish ineligible from absent.
3. Positive treatment net dollars and treatment-minus-control net advantage under
   existing costs AND a separately accounted $0.03/share/per-side slippage scenario.
   The stress price replaces baseline slippage, not another three cents added to it.
   Re-evaluate cash admission/reserves under stress; do not just subtract costs from
   an unchanged fill list and call it a feasible account result.
4. Complete liquidation-equity maximum drawdown no worse than control and <=$200.
5. Positive treatment P/L after removing its three best sessions; positive advantage
   after removing the three largest session contributions to that advantage. Ties
   resolved chronologically; report separate deletions rather than choosing favorable days.
6. No complete account-performance claim with unresolved exposure or valuation gaps.
   True zero-trade days have zero daily change only when full account valuation is known.

Uncertainty method `paired-overlapping-noncircular-five-session-blocks-v1`:
daily liquidation-equity changes for the same 60 sessions; 56 overlapping blocks
of five consecutive sessions; sample twelve blocks with replacement per replicate,
using identical indices for both arms. 10,000 replicates, fixed seed 20261027;
linearly interpolated percentile 95% interval of total treatment-minus-control
dollars. No dropping outages, imputation or treating trades as independent.
Unknown daily values return INCONCLUSIVE. Report the interval alongside every
gate; a positive point estimate alone is not evidence of reliable profitability.

## Concrete after-hours handoff plan — NOT executed

1. Review the five findings above, especially shared selection and cutoff semantics.
   This patch alone has nothing to activate. Finish the account/collector/persistence
   adapter on this branch only after the mapping is agreed.
2. Add integration tests for unchanged baseline output, first-ticker admission,
   Structured participation, settlement/closing reserves, exact contract collection,
   outages, early closes, restart/transaction idempotency, activation once, read-only
   endpoints, all coverage denominators and stress cash paths. Run repository checks.
3. Obtain review of the complete diff, exact spec hash and first prospective session.
   Only then approve push/merge and an after-hours deployment window separately.
4. During approved maintenance: hold new scans, let in-flight work finish, take a
   verified online SQLite backup and copy/hash it on main Mac; retain rollback images.
   Deploy disabled code and additive schema only; verify existing accounts/history,
   policies, settings and paper-only health. Do not restore old DB over new evidence.
5. Separately approve activation. In one transaction create both identities/funding
   events with actual UTC boundary and current watermarks. Verify $2,000 each,
   identical frozen account constraints, zero imported trades, exact 60-session calendar.
6. Resume intended scanner state and inspect first new events/quote evidence. Flag
   deployment boundaries and gaps; no historical reconstruction or silent tuning.

## Local validation

October 27: **335 backend tests passed**, including 47 new component/evaluation
cases; Ruff and Mypy (38 source files) passed; `git diff --check` passed. Two
existing dependency deprecation warnings remain. No frontend files changed, no
production database was used by tests, and no deployment/activation was performed.

Component tests cover both directions, breakout exclusion, five-bar expiry,
same-bar cancellation, pending invalidation, missing/invalid/conflicting candles,
stale/repeated/future/naive quote clocks, exact contract identity, failed liquidity
verification, original band, planning-risk extension, capacity skips, deadline,
cutoff/early-close rejection, serialization/idempotency, unknown valuations and
deterministic bootstrap. These do not substitute for the unimplemented account
and collector integration tests listed above.
