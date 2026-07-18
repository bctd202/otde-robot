# Known Limitations

- Phase 1 uses mock data only by default.
- Live market-data adapter is a non-fabricating placeholder.
- Chart Workspace is a responsive mock visualization, not yet an interactive candlestick implementation.
- Analytics does not label any setup statistically promising until enough real journal samples exist.
- Option-return estimates in Phase 1 are simple thresholds, not full Black-Scholes scenario grids.
- Journal records are seeded demo records; signal generation is not yet scheduled or persisted continuously.
- Analytics exposes basic seeded outcome aggregates only; drawdown and grouped reports remain later work.
- Holiday logic is a small deterministic Phase 1 calendar rather than a full exchange calendar package.
- WebSocket sends heartbeat state only; polling/reconnection and live update events remain Phase 2.
