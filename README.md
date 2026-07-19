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

1. Create a Railway service from this GitHub repository. `railway.json` selects the root Dockerfile.
2. Add a persistent Railway volume mounted at `/data`.
3. Set `MARKET_DATA_PROVIDER=mock`, `MOCK_SCENARIO=active`, `PAPER_ONLY=true`, and `DATABASE_URL=sqlite:////data/liquidity_hunter.db`.
4. Generate a Railway domain. The dashboard is at `/`, API documentation is at `/docs`, and health checks use `/api/health`.

Do not set live-provider or brokerage credentials. The container applies Alembic migrations and seeds an empty database before starting Uvicorn on Railway's `PORT`.

## Safety

- Mock status is explicit in every provider response and prominently visible in the UI.
- API credentials belong only in environment variables; `.env` is ignored.
- Lottery candidates can lose the entire displayed debit and never appear in structured rankings.
- Signals are generated only by deterministic Python rules.
