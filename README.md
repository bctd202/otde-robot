# 0DTE Liquidity Hunter

Local-first, deterministic research dashboard for SPY, QQQ, and IWM same-day option setups. Phase 1 uses mock data and is **paper-only**: there is no brokerage client, order router, or live-order execution path.

## Phase 1 status

Implemented: FastAPI APIs, mock quotes/candles/options, basic liquidity calculations, structured and lottery filters, SQLite persistence and seed data, journal/analytics reads, WebSocket heartbeat, React command center, risk labeling, Docker configuration, and automated tests.

Placeholders: live data, economic calendar, interactive production charts, alerts, scheduler, full option scenario pricing, realistic fills, replay, and production-grade analytics. See [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

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

To demonstrate a rules-valid NO TRADE dashboard, stop the backend, set `MOCK_SCENARIO=no_trade` in `.env`, and restart it. Restore `MOCK_SCENARIO=active` for seeded qualifying candidates.

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
`GET /api/parlays` endpoint scans the configurable `PARLAY_SYMBOLS` universe (at most 12 unique
symbols), filters today's contracts to $20–$100 ask cost, and assigns deterministic `PLAY`,
`WATCH`, `DEVELOPING`, or `PASS` labels. Missing credentials, upstream errors, missing same-day
expirations, and incomplete data fail closed and are reported explicitly rather than replaced
with mock data.

The production build log must list `/build/frontend/dist/index.html`, `/build/frontend/dist/favicon.svg`, and generated `/build/frontend/dist/assets/*` files. Container startup must print `Frontend build path: /app/frontend/dist`. If those lines are absent, Railway is not building the repository-root Dockerfile.

## Safety

- Mock status is explicit in every provider response and prominently visible in the UI.
- API credentials belong only in environment variables; `.env` is ignored.
- Lottery candidates can lose the entire displayed debit and never appear in structured rankings.
- Signals are generated only by deterministic Python rules.

## Option contract verification and demo data

Parlay only marks an option recommendation actionable when the exact contract and quote came from a successful current Tradier chain response. Verification checks the provider-returned OCC symbol without rewriting it, underlying, calendar-date expiration, strike, CALL/PUT type, bid/ask integrity, quote timestamp, configured freshness limit, and the existing spread and liquidity rules. A date-only expiration is never timezone shifted.

Data labels are explicit: **verified live** is current Tradier data, **verified delayed** is Tradier data with its delay shown, **demo** is intentionally generated mock data, and **unavailable/unverified** cannot be acted on. Enable demo mode only with `MARKET_DATA_PROVIDER=mock`. It displays `DEMO MODE — MOCK OPTION DATA — DO NOT TRADE`, never describes itself as live or delayed, and disables paper entry. The provider factory does not fall back to mock when Tradier or another provider fails.

When no listed contract passes verification, Parlay keeps useful underlying context visible and says **No verified contract available** with the reason. It does not invent a strike, expiration, OCC symbol, premium, Greeks, volume, or open interest, and it does not show an actionable contract instruction.

### Why older builds could show plausible mock contracts

The application setting and production image previously defaulted to the deterministic mock provider. That provider intentionally constructs synthetic option symbols, strikes, quotes, Greeks, volume, and open interest for development, while Lottery Lab rendered those fields without an expiration/OCC/provenance trust treatment. This was configuration-driven demo data, not a Tradier failure fallback—the provider factory never switched a failed Tradier request to mock—but an unset production provider could therefore look actionable. The application and production image now default to an unavailable provider; mock data requires an explicit environment setting and is never actionable.
