# Collection repair v2 — prepared for release review

This release repairs transport and prospective execution, with no change to entry scores, ticker selection, stops, targets, position counts, cash funding, or option-premium ceilings. No migration is required. No historical exits, missing candles or account values are reconstructed.

## Transport

The persistent DXLink client sends application KEEPALIVE at most every 30 seconds, shortened to half a positive negotiated server timeout. Busy feeds and quiet sockets both send heartbeats; receives time out within one second so stop remains responsive. A connection that worked for at least 60 seconds resets reconnect backoff to one second. Connection counts, disconnects and last keepalive time are inspectable.

After a two-minute opening grace, a stale configured symbol may queue a same-session subscription refresh. The stream processes up to three symbols per minute; a symbol is not refreshed again within 120 seconds. This uses the same socket and no REST requests, preserves the universe and does not manufacture empty bars. Per-symbol coverage is still necessary; a refresh cannot guarantee upstream availability. Late-arriving bars may inform future evaluations but never rewrite prior decisions or coverage observations.

Missing, malformed or timezone-less underlying/candle timestamps are rejected. They cannot default to the local clock. Regular-session and completed-bar selection remain intact. Tastytrade's application KEEPALIVE requirement is documented at https://developer.tastytrade.com/docs/concepts/streaming/ .

## Main account execution boundary

The ten-position account keeps its existing cash, policy JSON, old trades and unresolved exits. Each newly discovered position receives `execution_version=decision-clock-v2`. The first such opportunity appends exactly one zero-cash EXECUTION_BOUNDARY event. It does not fund or reset anything. The account graph spans this boundary, and the UI explicitly labels that mixed collection history.

For new positions only:

- An underlying candle event becomes observable at candle close, never before. Reject a newly discovered exit event more than 180 seconds after that close.
- Save the actual exit request and its completed-candle evidence. Once requested, use the existing 180-second deadline from that request; do not repeatedly apply an earlier deadline based on the candle's start timestamp.
- Require the same exact contract, live provider, known application receipt and upstream bid/ask times, freshness, and at least one-second post-decision latency. Entries still require full provider readiness.
- Held exits/valuations may use independently healthy option REST evidence during a candle-only disconnect. REST errors, stale data, wrong contracts and expired requests still fail. Held quote refreshes retain the existing request count and reserve.
- Legacy positions retain their original execution semantics, including existing UNPRICED outcomes. The old three-position account writer is unchanged.

Saved lotto quote receipts also identify collection-integrity-v2; the exit-rule accounts retain their balances, policies and earlier evidence. Compare collection cohorts explicitly before attributing changes to the strategy.

## Coverage and readiness

Each new scan saves actual transport-cache candle availability. The close pass inspects the final completed minute before releasing the stream and appends one DataQualityEvent under the scanner lock. It performs no new market request or trading evaluation. Late restarts cannot invent that observation.

The UI retains historical saved-evaluation counts and separately shows ticker-level input availability from the new instrumentation's actual start. Earlier scans are not reclassified. `/api/readiness` is read-only and distinguishes sleeping hours, stale scans, disconnected/stale symbol data, unknown exits and protected research drift. `/api/health` remains process liveness; Compose now checks that liveness. Restart-unless-stopped does not automatically restart an unhealthy process, and no automatic trading/account repair is added.

## Frozen retest study

The activated breakout-retest-v1 source guard includes the repaired feed/cache files. Its saved hashes, dates, records and evaluation requirements remain untouched. On deployment, source drift blocks NEW research admissions and records the original protocol's drift event; existing exposure continues through its saved rules. Read-only API/UI show the block immediately, even before another scan processes it. The old full-performance verdict remains INCONCLUSIVE.

This is deliberate preservation, not a new approved 60-session experiment. A successor comparison requires a separately versioned specification/implementation and explicit prospective activation; this release does not create another four accounts or move the original start/end dates.

## Main-Mac reports and backups

`ops/parlay_maintenance.py` runs on Main Mac and accesses Parlay-Mac through the existing `ssh parlay` connection. It writes local `status.json`, an append-only status-change log and verified compressed backups. No email or webhook is configured, per the user's preference.

Every five-minute invocation checks readiness. After 16:20 ET on weekdays, it backs up once per date. The source uses SQLite's online backup API and integrity check, then the runner copies a compressed snapshot off Parlay-Mac, restores it in an isolated temporary folder, verifies its SHA-256 and runs quick_check. Only after success does it remove the remote intermediates that this invocation created. A failed copy is not called verified. It keeps the newest 30 verified runner-owned local backups; manual/pinned archives are never pruned. Backups do not guarantee success if Main Mac is asleep/offline; overdue backups are reported.

Deployment must install the job explicitly; merely checking out code does not schedule it. Review the generated plist first:

```sh
python3 ops/parlay_maintenance.py --output /Users/ced/Documents/Parlay-Operations --print-launch-agent
```

Use a dedicated output directory and a durable Python 3.11+ interpreter. The printed plist uses the exact interpreter and script paths. Install as `com.parlay.maintenance` in Main Mac's user LaunchAgents after review; create its log directory before bootstrap. Keep the existing SSH trust configuration; the runner never changes it. No credentials are placed in the plist. User login, disk unlock and machine availability remain host prerequisites.

Run a first explicit off-hours backup with `--backup-now`, inspect `last-verified-backup.json` and status, then verify the loaded five-minute job. Its process lock prevents overlapping CLI invocations. Existing session backups are preserved. Local-only reports do not send a push notification when a machine is unattended.

## Release procedure

1. Pass complete backend/frontend checks, review the diff and preserve the pre-release database, environment, images and account event counts.
2. Push/merge only the reviewed revision. Deploy outside market hours; no schema change or account activation is required. Record the release UTC time and the automatic execution-boundary event at the first new opportunity.
3. Verify health/readiness, source drift being reported for the original retest study, unchanged policies/funding/old positions, next session schedule, and no legacy outcomes repaired.
4. Install the reviewed local maintenance job separately and verify a real off-machine backup/restore checksum before describing backups as operational.
5. During the next live session verify connection duration beyond multiple keepalive windows, per-symbol coverage, later-quote fills/exits and scan timings. Until then, tests establish implementation behavior, not repaired live coverage or profitability.

Any rollback after new trades must preserve those positions and events. Do not restore an old database over subsequent evidence or silently run repaired-version positions through the old writer.

## Verification — October 30, 2026

417 backend tests and 107 frontend tests passed; Ruff (including the maintenance runner), mypy, ESLint, TypeScript and production frontend build passed. Two existing dependency deprecation warnings remain. New coverage exercises keepalive across multiple negotiated timeouts on quiet/busy feeds, stable-session reconnect backoff, bounded subscription recovery, strict timestamp rejection, the missed-exit timeline, unchanged legacy deadlines/unknowns, exact one-time zero-cash execution boundaries, close-observation idempotency, read-only readiness and failure isolation, backup restore/checksum failures, local report deduplication and retention scope. UI tests verify coverage separation, the preserved-study admissions warning and mixed-version account labeling.

No live deployment, production activation, maintenance-job installation, new remote backup or post-repair real-market validation was performed in this implementation task. The existing production audit remains the pre-repair evidence boundary.
