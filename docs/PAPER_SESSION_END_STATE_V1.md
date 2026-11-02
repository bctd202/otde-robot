# Paper contract session-end state v1

Prepared local change; not production activation or deployment. This is a main ten-position account capacity/lifecycle change, not just a cosmetic rename. It does not add option exercise, brokerage execution or an expiry valuation model.

## Existing exits stay unchanged

The existing session policy requests a timed underlying exit 15 minutes before the regular exchange close (including early closes), in addition to existing stop/target exits. The option-account writer still requires the exact contract's fresh verified later quote and its existing decision deadline, receipt freshness, fees, slippage and settlement assumptions. A valid explicitly quoted zero bid is distinct from a missing quote, under the existing modeled-liquidation rules; it is not a guarantee of a broker fill. No new underlying exit rule, premium stop, ticker filter or live order is added here.

## Terminal monitoring state, not a fabricated sale

The ten-position writer moves OPEN/UNPRICED positions to `ENDED_UNRESOLVED` once the regular session on their saved contract expiration date ends. A longer-dated contract is not ended just because its entry date ended. A same-day display says **Session ended · exit price missing**; after the expiration calendar date passes it says **Expired · exit price missing**. The regular-session boundary is the paper account's monitoring cutoff, not an assertion about every product's last trading time or completion of exercise processing.

The first transition appends one zero-cash `LIFECYCLE_BOUNDARY` with `session-end-state-v1`. Each affected position appends a zero-cash `SESSION_END_UNRESOLVED` event with its previous state, original reason, saved expiration, original debit, session boundary and actual observation time. Existing cash events, quote evidence, P/L, account funding, stored policy JSON, prior equity observations and historical skips are not rewritten. The mutable current position projection records the new lifecycle state and transition provenance. The writer can classify existing historical missing exits when deployed; this is disclosed reconciliation, not a backfilled trade.

Ended monitoring no longer consumes a live paper-position slot or reserves a future simulated sale fee. Original entry debits remain spent. No proceeds, cash credit, closing fee or realized loss is invented. Available cash can rise only by removal of an unused closing-fee reserve; the cash ledger itself does not change. Previously skipped opportunities are never replayed.

Ended records remain part of financial uncertainty. Current valuations AND new equity snapshots include them in unknown exposure; account equity and total return remain null. Readiness retains the unknown-exit warning. No temporary removal from the active-position list may manufacture a complete portfolio graph.

This is not proof that an actual brokerage account is flat. In-the-money stock/ETF options can involve exercise; share delivery, do-not-exercise instructions, assignment, buying-power effects and broker confirmations are not modeled. Unsupported or missing outcomes remain unknown, never automatically marked as worthless. See the OCC/OIC exercise explanation: https://www.optionseducation.org/referencelibrary/faq/options-exercise .

## Presentation

Main Balance shows the number of ended unresolved contracts, original cost, known settled/unsettled cash, and a compact expandable list with expiration and 0DTE labels. Cash is explicitly not total equity or profit. Ended records leave the live-position list but remain visible in trade history and reconciliation. The graph headline explains missing exit proceeds, while old selected historical observations retain their original generic unknown-value explanation. A known sale awaiting settlement is labeled **Sold · awaiting settlement**.

Earlier baseline accounts, both lotto trial writers and the frozen retest study are unchanged. Their rules and balances are not silently converted to the main account's new capacity semantics. No new account or activation is created. Protected retest source files are untouched; its existing source-drift block remains in place.

## Review / release

No schema migration is required. Review the capacity change and pre-release backup, then deploy after hours only with user approval. The normal writer/startup reconciliation performs append-only transitions; GET endpoints never do. Verify the two October 29 records become ended unresolved, live slots are released, entry cash/P&L/funding remain unchanged, historical graph gaps remain gaps and readiness still reports missing proceeds. Do not retroactively call those contracts worthless or import unmatched shadow quotes as sales.

The patch also carries the previously installed, tested Main-Mac backup-only scheduling fix so a morning manual backup does not suppress the same day's closing backup. No maintenance job is installed or changed by this code task.

## Local validation — November 1, 2026

436 backend tests and 111 frontend tests passed. Ruff (backend and ops), mypy (46 source files), ESLint, TypeScript and the production frontend build passed. Two existing dependency deprecation warnings remain. Regression tests cover expiry/session boundaries, early closes and DST, longer-dated contracts, restart/idempotency, read-only GETs, historical preservation, unknown equity snapshots/readiness, no replay of capacity skips, no cash refunds, later-quote timed exits including explicitly quoted zero bids, and unchanged original-account processing.

An isolated temporary restore of the verified Friday backup passed its source checksum and dry-run reconciliation. Exactly the two expected missing-exit records changed projection state, with one lifecycle boundary and two zero-cash terminal events. Existing cash events, account policy and all other position records remained unchanged; missing equity remained null. No production database or source backup was modified. The temporary validation copy was discarded after testing. Trading rules and protected retest source files have no diff against deployed main.
