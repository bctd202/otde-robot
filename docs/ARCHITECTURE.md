# Architecture

The React/Vite client reads the FastAPI REST API; a heartbeat WebSocket is available for the future real-time loop. FastAPI delegates all quotes, candles, chains, and feed metadata through a provider interface. `MockMarketDataProvider` is deterministic and explicitly reports `mode=mock`; the live adapter fails closed and cannot place orders.

The setup service computes VWAP, opening range, swings, liquidity levels, structured candidates, and separately ranked lottery candidates. No LLM participates in calculations. SQLAlchemy persists market snapshots, candles, option contracts/quotes, setups, signals, paper entities, outcomes, reports, settings, and quality events. Alembic owns schema initialization; SQLite is the local default.

The dashboard, journal, and analytics endpoints are read-only in Phase 1. The seed command rebuilds a realistic demo dataset for SPY, QQQ, and IWM. React renders provider/account safety state before trade candidates and visually isolates the Lottery Lab.
