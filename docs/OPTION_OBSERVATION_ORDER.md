# Passive option-path collection order repair

Prepared November 12, 2026 for after-hours review. Do not deploy this change during
the exchange session. No migration, setting change or account activation is needed.

## Diagnosis

The GLD shadow sampler recorded a gap at 19:09:09 UTC on November 12. The main
paper account then recorded a verified quote receipt at 19:09:10 UTC for that same
held contract. The sampler had run before the account's existing chain refresh.
The cache expires after 20 seconds by default, so a quote from the previous
minute's scan is not an eligible cached chain. This is a local scheduling issue,
not evidence of a general feed outage.

AMZN's selected contract was skipped by the main account's entry-price limit.
Skipped positions do not receive the same held-position refresh priority. Both
contracts intermittently had good observations, but those do not repair their
missing minutes. Ten gap observations represented repeated checks on two
contracts, not ten failed trades.

## Change and limits

Move the existing cache-only sampler after baseline, frozen retest, expanded
account and optional debit-spread processing. Keep their relative order,
decisions, later-quote checks, exits and request reserves unchanged. The sampler
still makes zero data requests or subscriptions. It records the actual time it
runs, rather than assigning a later quote to an earlier clock.

The scan stores `option_observation_collection.version=after-account-refresh-v1`
and a separate sampling duration. Optional sampler failures roll back only its
observations and store an error type on the scan; completed account work survives.
No original research definition or strategy fingerprint is rewritten. Collection
timing changes prospectively; existing missing observations remain missing.

This fixes the observed before-refresh race when an account refreshes a chain.
It cannot guarantee quotes for price/capacity skips or every sampled contract.
Those remain explicitly missing when no existing consumer refreshed them. No
new provider traffic, looser freshness window or hidden backfill is introduced.
Option-path observations remain exploratory sampled evidence, not account fills
or a complete option-price history. New coverage must be measured after release.

## Validation and after-hours handoff

Regression tests cover refreshes in each existing account phase, once-per-minute
idempotency, missing/skipped contract coverage, stale and wrong-contract quotes,
immutable historical gaps, zero added requests and sampler failure isolation.
Existing baseline/account/retest/exit tests must continue to pass.

After market close: review the diff and checks; take and integrity-check the
existing database backup; verify the deployed revision and protected experiment
fingerprint; deploy the reviewed revision without migration/settings changes;
confirm healthy containers, paper-only mode, unchanged account policies and no
blocked retest admissions. Record the deployment boundary. On the next regular
session, compare sampling timestamps with held-position quote refreshes and count
quoted versus missing observations separately for held and skipped contracts.
After-hours liveness alone cannot prove next-session quote coverage.
