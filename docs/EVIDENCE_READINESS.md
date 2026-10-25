# Collection and option-evidence checks

This reporting patch does not alter trading decisions, historical rows, R calculations,
paper-account policies, or lotto exit experiments. No migration is required.

## Collection status

The workspace toolbar separates server connectivity from saved evaluations. During regular
hours, an evaluation more than 180 seconds old (or absent/future-dated) is overdue after a
three-minute opening grace period. A held scanner is labeled held; closed hours are sleeping,
not an active-session failure. This is an in-app indication, not an external notification.

Expand the status to inspect five trading sessions. Each bar counts distinct saved evaluation
minutes from regular open through completed minutes so far, or the regular/early close.
Repeated scans do not fill missing minutes. Holidays and weekends are excluded. Historical
gaps remain visible while the market is closed. Missing minutes are missing evidence, not
proof that no trading opportunity existed. A saved evaluation does not guarantee fresh
per-symbol candles, valid option quotes, or successful account finalization.

Next-opening timestamps are now converted to UTC before SQLite storage; previously, an
Eastern wall-clock time could be reinterpreted as UTC after its offset was stripped. The
independent scheduler's hours and trading rules have not changed.

## Historical option audit

History → Option execution shows the best entry-day gross option P/L, all other entry days
combined, and daily contribution bars. This is a concentration diagnostic, not deletion of
the best day or a cash-account return. All currently selected quoted rows remain in the
existing totals; gaps and untracked selections are not silently priced at zero.

Review flags identify missing quote timestamps, quotes after the saved observation timestamp,
exit quotes more than 60 seconds after the underlying event, and exit values at least 5× entry.
The thresholds are diagnostic only. Up to ten flagged examples are displayed by absolute P/L.
The legacy recorder uses a provider-status timestamp for observation time, not a confirmed
per-quote receipt timestamp. Therefore a sequencing flag is not proof of invalid data.

Reporting lives outside fingerprinted strategy/performance modules to preserve the current
research definition. Forward cash accounts remain separate from these gross historical marks.

## Verification and limits

- Backend: 252 tests passed; Ruff and mypy passed.
- Frontend: 85 tests passed; ESLint, TypeScript and production build passed.
- Synthetic browser checks passed at iPad and phone sizes, with no runtime errors
  or horizontal overflow. Screenshots were visually reviewed.
- Trading/performance, session input, account and lotto policy modules unchanged against main.
- Tests use isolated databases; no production records or configuration changed.
- This patch cannot repair October 19–23's absent scans or validate the corrected baseline
  retrospectively. The next real market session must provide fresh forward evidence.
- Deployment requires a verified backup, passing release checks, and post-startup health checks.
