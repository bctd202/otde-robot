# Architecture

The React/Vite client reads the FastAPI REST API; a heartbeat WebSocket is available for the future real-time loop. FastAPI delegates all quotes, candles, chains, and feed metadata through a provider interface. `MockMarketDataProvider` is deterministic and explicitly reports `mode=mock`; `TradierMarketDataProvider` uses market-data endpoints only, fails closed, and cannot place orders.

The setup service computes VWAP, opening range, swings, liquidity levels, structured candidates, and separately ranked lottery candidates. No LLM participates in calculations. SQLAlchemy persists market snapshots, candles, option contracts/quotes, setups, signals, paper entities, outcomes, reports, settings, and quality events. Alembic owns schema initialization; SQLite is the local default.

The dashboard, journal, analytics, and Parlay ranking endpoints are read-only. The seed command rebuilds a realistic demo dataset for SPY, QQQ, and IWM while the configurable discovery universe can be larger. React renders provider/account safety state before trade candidates and visually isolates the Lottery Lab.
