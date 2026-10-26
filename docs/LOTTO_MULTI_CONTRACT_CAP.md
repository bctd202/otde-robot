# Lotto v3: $100 contract premium, multiple positions

## Scope and frozen policy

Prepared for review only. No deployment, production setting change, migration or activation
is authorized by this patch itself. No live brokerage orders. The one-minute/retest experiment,
Structured Intraday, main cash account and historical results are not changed.

Two new identities: `lotto-v3-contract100-multi5-fixed5` and
`lotto-v3-contract100-multi5-trail40`. Each is an independent $500 paper account; never sum
these balances as one portfolio.

- One standard 100-share contract per entry. The verified ask must be at most $1.00:
  $100 premium, **before** modeled slippage and fees. No rounding an above-limit ask down.
- Existing costs: $1 slippage per contract on each side, $1.50 opening costs, $0.50 closing
  costs. A $1.00 ask costs $102.50 to enter and requires another $0.50 of reserved cash.
- No separate daily spending cap. No use of unsettled proceeds.
- Up to five occupied slots per account. Pending entries and unknown exits consume slots.
  Closing costs for every held/unknown position are reserved before admitting another fill.
- One selected contract per ticker/day across calls and puts; no simultaneous call and put
  on the same ticker. Multiple different tickers can be active together.
- Deterministic discovery ordering and score/spread rules are retained. The collector still
  keeps its existing ranked shortlist (up to three per direction per scan), **not every
  listed contract**. Unlimited opportunity-level exit comparisons are a separate future task.
- Entry uses a fresh later quote at least one second after its request, within 120 seconds.
  The current spread rule, quote freshness, 180-second exit deadline and settlement remain.
- Unchanged exits: 5x trigger or 40% trail armed after 2x, later-quote fills, no premium stop
  before the trail arms. Existing entry and exit session cutoffs remain unchanged.
- A low contract cost is not proof of low aggregate risk: several positions can lose their
  premiums together. Unknown exposure is never converted to zero or hidden by a reset.

## Discovery and compatibility

Repository discovery defaults previously capped ask at $0.40 and debit at $40. Those settings
remain untouched until explicit v3 activation. Once both v3 accounts exist and their activation
time has arrived, the collector uses the $100 premium ceiling and tags **new** snapshots with
`lotto-call-session-v3` / `lotto-put-session-v3` and `contract_premium_cap_cents: 10000`.
Other eligibility and shortlist rules are unchanged; widening the premium range can change
ranked selections and is an explicit part of this new version.

No prior tracker is re-labeled or imported. Same-day contracts discovered before activation
remain old evidence. For a clean cohort boundary, activate before the next chosen session,
not midway through its scan stream.

## Activation and old experiments

`activate_multi_trials(db, now=actual_utc_time)` is an explicit operator service operation,
not called by startup, scheduled scans or API reads. Both accounts are created in one
caller-owned transaction, funded once, with a real activation timestamp. Repeating activation
does not reset balances or change policies. Partial activation is rejected for review.

After activation, old experiments stop accepting newly discovered opportunities. Existing
pending entries finish their original deadline checks; entered positions continue their old
exit and settlement rules, and unknown positions stay recorded. Old policies and positions
are preserved, with an append-only retirement event. Before activation all legacy behavior
continues. No API activation button/endpoint is introduced.

The UI defaults to v3 only after activation. Previous versions remain selectable under
“Other experiment versions.” Unactivated v3 previews show no funded balance. Trades default
to entered positions; waiting entries and skipped opportunities have independent paginated
views. Whole-account balances and directional totals do not change with those filters.

## Review and after-hours rollout plan — not executed

1. Review the diff and approve this lotto-only scope separately from retest research.
2. Run repository checks and CI, take an online database backup, and retain rollback images.
3. Deploy the code without activation. Confirm health, unchanged legacy policies and records,
   read-only summaries, and no v3 funding/positions. No migration is needed.
4. Obtain separate approval for the first forward session and one-time activation. During an
   after-hours maintenance window, use one database transaction to call the activation service
   with actual UTC time. Do not backdate or copy positions.
5. Verify exactly two v3 funding events, $500 per account, five slots, $100 premium ceiling,
   no daily cap, and unchanged historical policies. On the next session verify v3 discovery
   evidence, genuine later-quote entries, total cash and fee reserves, then watch coverage.
6. Do not reset funded research accounts to undo a deployment. Before activation, code rollback
   is straightforward. After activation, pause new entry processing operationally and review
   how existing exposure will be managed before any rollback.

## Validation

265 backend tests and 88 frontend tests pass; Ruff, mypy, ESLint, TypeScript and build pass.
New tests cover exact/over-cap premiums, costs outside the ceiling, daily spending above $100,
mixed calls/puts, five slots including pending/unknown, same-ticker protection, fee reserves,
unsettled funds, later-quote execution, deadlines, independent exits, restart/idempotency,
read-only filtered pagination, deliberate activation, no backfill, legacy preservation,
and scanner discovery switching only after activation.

Existing receipt-timestamp limitations are not repaired by this patch; the separate evidence
work remains necessary. Stored quotes and simulated fills are not guaranteed brokerage fills.
