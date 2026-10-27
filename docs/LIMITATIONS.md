# Known Limitations

- Mock data remains the safe default; Tradier use requires an explicitly configured read-only token and `TRADIER_DATA_MODE=live` or `delayed` selected from the account's actual entitlement. `unknown` is deliberately non-actionable.
- Browser notifications require an open page. The server still scans and stores history while the page is closed, but email/SMS/Slack delivery is not configured.
- Analytics does not label any setup statistically promising until enough real journal samples exist.
- Option-return estimates in Phase 1 are simple thresholds, not full Black-Scholes scenario grids.
- Forward cash-account and lotto trial fills model fixed fees/slippage and later-quote ask entries/bid exits. They do not prove displayed size, queue position, partial fills or actual broker execution. Historic sampled ask-to-bid shadow observations are a different evidence series, not those cash accounts.
- The current money-first UI leads with simulated account value and net trade outcomes. Underlying-path R remains in the research view: it is not option P/L or portfolio return. Old shadow and R histories are not backfilled or rewritten. Research R analytics use the first BUY per ticker/day, exclude manual-origin positions, and quarantine cross-session, data-gap and zero-risk outcomes; account reports follow their own frozen admission/cost policies.
- Actual quote-receipt evidence is collected prospectively from release #45. Provider updated-at still supplies a shared quote timestamp, not independently verified bid/ask event times. Historical rows have no invented receipt clocks. See [quote evidence and timing](QUOTE_RECEIPTS_AND_SCAN_TIMING.md).
- The breakout/retest comparison is preparation only, not an active experiment. Its isolated timing component is not connected to scanning/accounts. See [scope, unresolved integration decisions and evaluation proposal](RETEST_RESEARCH_PREPARATION.md).
- Structured Intraday v1 uses same-session 1M data to build its slower context and intentionally produces no setup before one full session hour is complete. A future swing product will require multi-day daily/4H history and separate overnight rules.
- The market-data cache and 100-request safety guard are process-local. Multi-worker deployment needs a shared cache and distributed rate limiter.
- Holiday logic is a small deterministic Phase 1 calendar rather than a full exchange calendar package.
- The server scheduler assumes a single application worker. Multi-worker deployment needs a distributed scheduler lock.
- Automatic exchange-day sleep uses the published NYSE holiday and early-close calendars through 2028. Extend the calendar table before operating in 2029.
- WebSocket sends heartbeat state only; the UI currently polls the persisted cache for updates.
