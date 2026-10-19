# Corrected Tastytrade trial — October 19, 2026

This is a separate paper experiment, not a recovery of the old account's losses,
a broker account reset, or live order execution. The entire old research history
remains available. No signal R, option shadow outcome, or manual/lottery record is
recalculated by the account transition.

## Permanent identity and starting boundary

- Active account key: `tasty-session-v2-20261019`.
- Scheduled start: October 19, 2026, 09:30 America/New_York (13:30 UTC).
- Funding: exactly $2,000 simulated cash, one immutable FUNDING event.
- Before that boundary, scanner initialization/processing creates nothing. GET
  shows Scheduled and does not pretend funds have already been deposited.
- Actual activation is the first account-processing call on/after that boundary.
  If the machine starts late, the actual timestamp is saved; missing trading
  hours are not backfilled. Startup alone is not proof that the feed is healthy.
- The entry-mark watermark excludes all marks already present at activation.
  Older creation timestamps are also rejected. A first saved equity observation
  records the actual $2,000 funding and 0% return, not an invented past curve.
- The key never rolls daily/weekly, and restarts do not deposit more money.
  `PAPER_MONEY_STARTING_CASH` still controls existing research/replay uses, but
  cannot restate this trial's approved funding or frozen policies.

## Admission and risk assumptions

Both automated engines share the new account's capital and existing risk caps.
An entry must have live Tastytrade provenance, `current-session-v2` evidence for
its trading date, and one of the frozen versions:

- `ONE_MIN_0DTE`: `parlay-v1-session-v2`
- `STRUCTURED_INTRADAY`: `structured-intraday-v1-session-v2`

Nonmatching marks get an explicit SKIP event, not a simulated fill. Refreshed
entry, valuation and exit quotes must also be from Tastytrade. There is no silent
fallback to a different provider. Scanner decisions are not changed by these
account admission checks. A future strategy change needs an explicit new trial
decision, not an unnoticed blend into this baseline.

One contract per entry, three concurrent positions, the $100 entry budget,
settlement restrictions, later-quote requirement, modeled fees/slippage and
underlying exit rules are unchanged from the prior account. Missing prices
remain unknown. An unpriced new-trial position still uses capital and a slot.
Lottery and manual trades remain separate experiments.

## Legacy accounts

`forward-cash-v1` and any other noncurrent account are read-only. No account
rows, cash events, positions, or snapshots are altered to mark them archived;
the active identity determines that status. Their old OPEN/UNPRICED positions
are not liquidated, forgiven, transferred to new cash, or valued at entry cost.
Pending settlement is left in its original recorded state too. Any held legacy
exposure makes its current complete equity unknown. Saved historical valuations
remain inspectable as dated observations.

`GET /api/forward-paper-account` defaults to the corrected trial and includes an
account catalogue. `?account_key=forward-cash-v1&page=1` reads the preserved
account. Unknown keys return 404. All reads remain nonmutating. The dropdown
resets pagination and clears the prior account display while loading.

The wider historic research ledger remains available; the selector changes only
the account view, not the historical scanner, backtest, or lottery datasets.

## Verified pre-deployment archive

Before deployment, pause the scanner through the existing operator hold, allow
the in-flight scan to finish, and resolve the actual database path and current
deployed revision. Do not print `.env` or credentials. Run the new helper in an
environment that has the code and access to the source database:

```text
PYTHONPATH=backend python -m app.services.research_archive SOURCE.sqlite ARCHIVE.sqlite --revision DEPLOYED_COMMIT
```

These are placeholders, not a deployment command to paste unchanged. The helper
uses SQLite's online backup API (including committed WAL contents), copies all
tables, runs `integrity_check`, writes table counts and SHA-256 to a sidecar
manifest, and makes both files read-only. It refuses to overwrite an existing
archive. A failed operation must not be called verified; inspect its error and
use a new filename. Copy the database and manifest to the main Mac and verify the
SHA-256 before migrating/restarting. Keep that copy outside the active data
volume. Do not use a raw file copy of a running WAL database.

After deployment verify the scheduled/active status, account identity, exactly
one new funding event once activated, absence of imported positions, unchanged
legacy records, Tastytrade quote/session health, and paper-only mode. Restore the
operator's intended hold/resume state. There is no automatic production backup
or live deployment merely from running tests or reading the dashboard.

## Money-first UI

Lead with one account-return graph and simple per-trade outcomes. For completed
paper trades, use cash spent including modeled entry costs, net proceeds after
modeled exit costs, dollar profit/loss, and net trade return on that debit. Keep
underlying R/raw/directional movement in a Research/Details area, not competing
with option-dollar profitability. Open positions show an estimate and quote
age; missing exits show Unknown. Lottery peak multiples are explicitly hindsight
peaks, never labeled as a captured exit. Any multiple must state whether it is
gross option-price or net cash returned relative to cash spent.

The main view now leads with account value and paginated trade outcomes. The prior
strategy-performance metrics remain under Research; their calculations are unchanged.
See [Lotto forward trials](LOTTO_FORWARD_TRIALS.md) for the separate prospective
CALL/PUT and fixed/trailing experiments, policies and limits.

## Local verification — October 17

212 backend tests and 66 frontend tests passed, along with Ruff, Mypy, ESLint,
TypeScript and the production frontend build. Added regression coverage includes
the scheduled boundary, actual activation timestamps, one-time funding, legacy
row preservation, provider/input/version isolation, read-only account selection,
pagination reset, and a verified WAL-aware archive that cannot overwrite prior
files. Chrome checks with explicitly synthetic data passed at desktop, 390px and
320px, including active/archived/scheduled switching and unknown-value gaps.
No production backup, merge, deployment or live fill verification occurred.

October 18 follow-up: the money-first layout and separate lotto experiments are
implemented; see `LOTTO_FORWARD_TRIALS.md`. Combined verification is now 238 backend
tests and 73 frontend tests, plus lint/type/build and synthetic desktop/mobile checks.
