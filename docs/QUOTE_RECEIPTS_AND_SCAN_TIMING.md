# Quote evidence, scan timing, and compact board tools

## Scope

Prospective collection-integrity fixes and presentation only. No new brokerage execution,
account activation/reset, starting cash, capacity, premium ceiling, entry band, universe,
score, stop, target, or exit-rule changes. Existing accounts and historical outcomes are
preserved. The one-minute breakout/retest treatment remains a separate, unimplemented task.

The source fingerprint for the baseline strategy/research modules is unchanged. A data-path
fix can nevertheless affect future eligibility and simulated fills: missing upstream quote
times are no longer substituted with the local clock, and actual receipt freshness now
participates in paper execution. Do not portray this as an identical-data comparison with
the prior collector. Record the deployment revision/time as the evidence boundary.

## Actual receipt evidence

- Each Tastytrade option REST response gets a local UTC receipt timestamp when the response
  has been decoded, before waiting for Greeks/Summary data. Each batch has its own receipt.
- Cache reuse retains that timestamp. A subsequent scan never makes an old response new.
- `OptionContractOut.received_at` and `receipt_basis=REST_RESPONSE_RECEIVED_V1` carry it through
  existing caches and contract copies. This is application receipt, not exchange execution time.
- Missing, malformed, or timezone-less upstream option timestamps are rejected instead of
  falling back to now. Supported numeric epoch seconds/milliseconds remain supported.
- Lotto migration `0017_quote_receipt` adds nullable `receipt_evidence` only. Old rows keep
  null; no historical transport timestamps are invented. The legacy database `received_at`
  remains processing time for compatibility; new JSON explicitly separates both clocks.
- New lotto snapshots with unknown, stale, future, or pre-decision receipt cannot support a
  new paper fill. Legacy snapshots retain their labeled old semantics; no historical replay.
- Main paper-account quotes also require known Tastytrade receipt provenance, within the
  existing 60-second freshness window and after the existing decision/latency boundary.
  Entry/exit events and valuations retain the receipt evidence.
- Paper execution still requires the existing exact contract and quote-price checks. Costs,
  120-second entry/180-second exit deadlines, capital/slot treatment, and settlement stay fixed.

## Coverage and speed

The October 26 diagnostic found 324 saved scan rows and 102 completions more than 60 seconds
after their evaluation candle closed (median completion lag 51.07s, maximum 93.78s). These
include scheduling latency and work time, and are **not** phase measurements. The coverage
panel counted 323 distinct regular-session evaluation minutes out of 390; row count is not
the same as regular-minute coverage.

Previously every bounded DXLink metric request waited the full timeout even after receiving
every requested Greek/Summary pair. It now finishes early only after every requested
event-type/symbol pair arrives. Duplicate events cannot satisfy missing pairs. Partial
responses still wait until their original timeout; candle history always retains its full
collection window. No stale-metric cache, reduced freshness threshold, narrower universe,
new requests, overlapping scans, or weakened API reserve was introduced.

New saved scans include monotonic work timings for one-minute ranking, Structured Intraday,
lifecycle/shadow work, lotto processing, main account/observations, and alerts. The read-only
collection panel summarizes measured scans among the last 120 saved scans in five sessions,
including p95 duration, runs at least 60 seconds, and latest phase durations. No old timings
are inferred. Failed runs and final-commit duration are not covered by these success timings;
runtime errors remain in the existing scanner health view. Real-session coverage must be
measured before claiming the missing-minute problem is solved.

## Board controls

Play Selector, Flex Scanner and Signal Alerts start as compact native dropdowns, with current
view, used slots, and recorded alert count visible. They support keyboard opening and keep
their child components mounted, so closing a panel does not discard a ticker draft or alter
alert preferences. Browser notification polling remains outside the dropdowns; closed panels
do not stop scanning. Multiple panels may be opened, including on narrow phone screens.

## Validation / rollout

Tests cover receipt transport timing, cache reuse, missing/bad upstream timestamps, stale/future
and pre-decision receipts, persisted provenance, full/partial/duplicate DXLink metric packets,
unchanged candle-window collection, additive migration/history preservation, bounded scan
diagnostics, and board-control state. Run full backend tests, Ruff/mypy, frontend tests,
ESLint/TypeScript/build, and the synthetic iPad/phone interaction check before release.

Before deployment: back up SQLite online, retain rollback images, verify the activated lotto
accounts/policies and existing records, run CI, then apply the additive migration through the
normal container entrypoint. Confirm no account resets, new default v3 accounts retained,
health/served bundle, and zero rewritten preexisting columns. Record the deployed boundary.
At the next session verify new receipt evidence and actual scan coverage; do not backfill
missed trades or loosen the account rules to increase apparent results.

## Still not brokerage fills

The adapter's provider `updated-at` remains a shared timestamp for bid and ask, not proven
independent side timestamps. We do not have queue position, guaranteed displayed size, partial
fills, or actual broker execution reports. The historic ask-to-bid shadow and older sampled
observations keep their original evidence labels and limitations. These fixes improve forward
paper evidence; they do not establish profitability or guarantee execution.
