# 0DTE Liquidity Hunter

Local-first, deterministic research dashboard for SPY, QQQ, and IWM same-day option setups. Phase 1 uses mock data and is **paper-only**: there is no brokerage client, order router, or live-order execution path.

## Phase 1 status

Implemented: FastAPI APIs, mock and read-only Tradier market data, shared market-data caching and request-budget protection, deterministic 1-Min/0DTE and Structured Intraday engines, an always-on completed-candle signal engine, durable per-strategy lifecycle and alert history, SQLite persistence, paper positions, normalized live performance tracking, chronological 1-Min backtests, React command center, risk labeling, Docker configuration, and automated tests.

Placeholders: economic calendar, external push delivery when the browser is closed, full option scenario pricing, realistic fill modeling, and production-grade grouped analytics. See [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Native macOS setup

Requirements: Python 3.12, Node.js 20+, and npm.

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
npm --prefix frontend install

# From the repository root: create schema and deterministic demo records.
PYTHONPATH=backend alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend python -m app.db.seed
```

Start each process in a separate terminal from the repository root:

```bash
# Terminal 1
source .venv/bin/activate
PYTHONPATH=backend uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2
npm --prefix frontend run dev -- --host 127.0.0.1
```

Open **http://127.0.0.1:5173**. API docs are at **http://127.0.0.1:8000/docs**. The SQLite database is `./liquidity_hunter.db`; safe local configuration is `./.env`.

Mock mode provides underlying research data but does not create option contracts. Synthetic contracts require the explicit `ENABLE_DEMO_OPTION_CONTRACTS=true` switch, are labeled **DEMO MODE — MOCK OPTION DATA — DO NOT TRADE**, and can never be entered or included in live Performance metrics. To demonstrate a rules-valid NO TRADE dashboard, set `MOCK_SCENARIO=no_trade` and restart.

## Verification

```bash
PYTHONPATH=backend pytest backend/tests
.venv/bin/ruff check backend
.venv/bin/mypy backend/app --ignore-missing-imports
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/dashboard
```

## Docker

```bash
cp .env.example .env
docker compose up --build
```

Docker persists SQLite under the named `app-data` volume and seeds the demo on startup. Keep both `backend` and `frontend` services running while using the dashboard.

## Railway (single service)

The root `Dockerfile` builds React, verifies its generated `index.html` and `assets` directory, and copies `frontend/dist` to `/app/frontend/dist` in the FastAPI image. `FRONTEND_DIST_DIR` pins FastAPI to that exact location, which is printed during container startup. FastAPI serves the API and the compiled frontend from the same Railway domain; frontend requests use the same-origin `/api` path.

1. Create a Railway service from this GitHub repository with its **Root Directory left empty (repository root)** and no dashboard-level Dockerfile override. `railway.json` selects the only backend-capable Dockerfile, at `/Dockerfile`.
2. Add a persistent Railway volume mounted at `/data`.
3. Set `MARKET_DATA_PROVIDER=mock`, `MOCK_SCENARIO=active`, `PAPER_ONLY=true`, and `DATABASE_URL=sqlite:////data/liquidity_hunter.db`.
4. Generate a Railway domain. The dashboard is at `/`, API documentation is at `/docs`, and health checks use `/api/health`.

Do not set live-provider or brokerage credentials. The container applies Alembic migrations and seeds an empty database before starting Uvicorn on Railway's `PORT`.

## Tradier market data and Parlay scanner

Tradier is an optional, read-only market-data provider; no order endpoint is implemented. Set
`MARKET_DATA_PROVIDER=tradier` and provide `TRADIER_API_TOKEN` through the environment. The
The server scans the configurable `PARLAY_SYMBOLS` universe (20 unique symbols) after each
completed one-minute candle. The 1-Min engine filters today's contracts to $20–$100 ask cost, and assigns deterministic `PLAY`,
`WATCH`, `DEVELOPING`, or `PASS` labels. Missing credentials, upstream errors, missing same-day
expirations, and incomplete data fail closed and are reported explicitly rather than replaced
with mock data.

The Structured Intraday engine runs in parallel without locking out the 1-Min engine. It requires one hour of session context, aligned 1H direction and session VWAP, a reclaimed 15M liquidity sweep, a 5M market-structure shift, a controlled retest, at least 2R to the first target, and a verified liquid contract with 5–14 calendar DTE. Both engines remain visible under **All plays**; the selector only filters the board, and browser alerts can be enabled independently for each engine. Every lifecycle, paper position, and performance row stores its strategy mode and rules version.

One process-wide read-through cache shares quotes, 1M candles, expirations, and exact option chains across the scanner, both engines, entry checks, position management, and legacy context panels. 5M, 15M, 1H, and 4H views are aggregated locally from the cached 1M session feed. Expirations are cached for the trading day and option chains are requested only after the underlying setup qualifies. The Tradier adapter enforces a configurable 100-request/minute safety budget below the upstream 120-request limit and reports remaining capacity on the board. Browser polling reads persisted scans and server-owned paper-position marks; it does not initiate normal market-data refreshes.

The browser reads the latest persisted scan every 15 seconds; it no longer initiates market-data work. The server scanner itself runs once per minute at second 5, after the prior one-minute candle has closed. APScheduler permits only one running scan, coalesces missed executions, and uses a 30-second misfire grace period so a resumed machine does not replay a stale backlog. Signal state survives restarts and follows `WATCH → BUY → ENTERED / EXPIRED / MISSED / INVALIDATED`. BUY cards include their last verification and next-evaluation deadline. The server records lifecycle, entry-window, target, and stop events under `/api/signal-alerts`; the dashboard keeps the history and can show browser notifications while the page is open. The scheduler continues scanning with the page closed and reports `idle_market_closed` without evaluating signals outside regular hours.

The default universe is `SPY,QQQ,IWM,TSLA,NVDA,AAPL,AMZN,META,MSFT,GOOGL,AVGO,IBIT,GLD,SLV,TLT,USO,UNG,AMD,COIN,PLTR`. `PARLAY_SYMBOL_LIMIT` changes the permanent-universe cap. The dashboard also provides two database-backed **Watch Today** slots. Flex symbols are validated against the configured provider, included in the same deterministic scan, and automatically disappear on the next New York trading date.

Set `TRADIER_DATA_MODE` explicitly from the account's actual market-data entitlement: use `live` only after real-time entitlement is verified, or `delayed` for delayed quotes. The production base URL does not prove entitlement, so Parlay never guesses it. The safe default `unknown` emits a configuration warning and remains non-actionable; delayed mode is also research-only. Execution remains paper-only in every mode. Every displayed actionable option requires `TRADIER_DATA_MODE=live` and is the exact OCC symbol returned by the successful Tradier chain request. The server independently parses and compares its root, expiration, strike, and call/put identity, then separately enforces current `bid_date` and `ask_date`, positive crossed-safe quotes, spread, volume, open interest, expiration, and strategy liquidity rules. Failed contract verification preserves the underlying setup while reporting **No verified contract available** and suppressing every option field. Paper entry reruns the selected strategy's complete underlying setup, no-chase test, selected contract, expiration policy, and current Tradier verification on the server; a stale browser BUY is rejected. Browser-supplied provenance, prices, levels, and score are never trusted. Migration `0006_contract_provenance` records the contract audit trail, `0008_signal_engine` adds durable scan, lifecycle, alert, and engine-health state, and `0009_trading_modes` adds strategy identity plus normalized return tracking.

The production build log must list `/build/frontend/dist/index.html`, `/build/frontend/dist/favicon.svg`, and generated `/build/frontend/dist/assets/*` files. Container startup must print `Frontend build path: /app/frontend/dist`. If those lines are absent, Railway is not building the repository-root Dockerfile.

## Safety

- Mock status is explicit in every provider response and prominently visible in the UI.
- API credentials belong only in environment variables; `.env` is ignored.
- Lottery candidates can lose the entire displayed debit and never appear in structured rankings.
- Signals are generated only by deterministic Python rules.

## Performance tracking and Backtest Lab

Parlay now separates **live forward tracking** from **historical backtesting**. Every qualified live BUY is frozen in a persistent signal ledger even when the user does not enter a paper position; manually entered paper positions are linked to that record rather than defining whether the signal is measured. Historical runs replay regular-session 1-minute candles chronologically through the same production setup evaluator used by the live scanner and never route a paper or brokerage order.

Historical outcomes are measured on the underlying against the original entry-to-stop distance. Performance can toggle between **R Multiple** (`price movement / initial underlying risk`) and **Return %** (`signed underlying move / original entry`). The original entry and stop are frozen when the signal triggers, so a later management decision cannot rewrite its R result. Tradier plans may return limited or incomplete intraday history and do not provide enough expired option quotes to reconstruct honest contract P&L, so Parlay does not synthesize or claim historical option returns. Partial ranges and per-ticker failures remain visible.

Performance metrics exclude open signals from win rate, average/cumulative R, profit factor, and maximum drawdown. Win rate is positive-R completed signals divided by completed signals; profit factor is gross positive R divided by absolute gross negative R; drawdown is the largest peak-to-trough decline in the chronological cumulative-R curve. MFE and MAE are the greatest favorable and adverse underlying excursions divided by initial risk. Duration is trigger-to-exit minutes.

When a candle touches both stop and target and tick order is unavailable, Parlay conservatively records the **stop first** and marks the audit record. Intraday positions receive a timed exit at the strategy session cutoff rather than being carried overnight. Event timestamps are stored as timezone-aware UTC and displayed in `America/New_York`; option expirations remain calendar dates. Older ambiguous paper timestamps are intentionally not migrated.

Open **Backtest Lab**, select dates and configured tickers, and choose **Run Backtest**. The latest completed result stays visible, overlapping submissions are rejected, and saved history includes requested/available ranges plus ticker failures. Open **Performance** to filter by strategy as well as live, manually entered paper, historical, open, or completed records. Use **Return %** for the quickest glance or **R Multiple** to compare risk-normalized execution, then expand a row for its frozen strategy version, original risk, conditions, option-at-trigger snapshot, and conservative-resolution marker.
