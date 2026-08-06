# Known Limitations

- Mock data remains the safe default; live Tradier use requires an explicitly configured read-only token and verified data mode.
- Browser notifications require an open page. The server still scans and stores history while the page is closed, but email/SMS/Slack delivery is not configured.
- Analytics does not label any setup statistically promising until enough real journal samples exist.
- Option-return estimates in Phase 1 are simple thresholds, not full Black-Scholes scenario grids.
- Paper fills use the current ask for entry and defensible bid for liquidation; they do not model queue position, slippage, or partial fills.
- Live performance is measured honestly on the underlying in R because expired historical option quotes are not available.
- Structured Intraday v1 uses same-session 1M data to build its slower context and intentionally produces no setup before one full session hour is complete. A future swing product will require multi-day daily/4H history and separate overnight rules.
- The market-data cache and 100-request safety guard are process-local. Multi-worker deployment needs a shared cache and distributed rate limiter.
- Holiday logic is a small deterministic Phase 1 calendar rather than a full exchange calendar package.
- The server scheduler assumes a single application worker. Multi-worker deployment needs a distributed scheduler lock.
- WebSocket sends heartbeat state only; the UI currently polls the persisted cache for updates.
