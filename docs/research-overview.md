# Main-account research overview and exact data exclusions

On November 4 the user approved excluding the three previously written-off
positions from the main research results because their exits were unscorable.
The exclusion definition is tied to the exact prior approval-request hash, three
positions and $179.50 total original debit. It is **not** a rule excluding every
missing quote, write-off, loss, provider or ticker.

## Main screen

- One **Adjusted research value** graph and included-trade gain/loss.
- Actual available paper cash, explicitly distinguished from research value.
- All open/pending/unpriced live positions, independent of trade-history pages.
- Five recent completed trades, independent of trade-history pages.
- A compact **3 data exclusions** link to a separate archive.

Account details retain actual balances, the complete cash ledger, manual
write-offs, policy/methodology notes and earlier collection boundaries. Archived
accounts retain their existing view. Active processing failures and included
missing values remain visible; simplification does not turn them into success.

## Meaning of the research value

This is a derived cohort comparison, **not refunded cash, buying power or a
funded-account return**. For the excluded positions, original entry debits are
removed from the comparison and their option exposure is removed too. Keeping
their historical bids while adding back the debit would double-count value.

At a saved observation, the curve uses saved cash and timestamp-valid retained
position values under the existing valuation policy, plus the exact excluded
entry costs incurred by that time. Full captured-position coverage must agree
with the positions' entry/exit/write-off times and original unknown-value count.
An original null may become calculable in this separate derived series only if
all its unknown exposure was explicitly excluded. Any other missing valuation or
incomplete position evidence leaves a gap.

No historical snapshot, quote, actual cash event, manual adjustment, underlying R,
other account, rule, or buying-power policy is rewritten. No previously skipped
trade is replayed using hypothetical extra capital. Exclusions based on data
availability may bias the remaining sample; these figures do not establish an edge.

For the previously inspected November 3 closing state, this comparison would show
$2,074.00 (+$74 / +3.70%), while actual account value remains $1,894.50. Those are
different concepts and have separate labels. These are example snapshot figures,
not a promise about the current live balance.

## Read-only API

`GET /api/forward-paper-account` retains all existing monetary fields unchanged.
It adds `research_view`, `data_exclusions`, `open_trades` and `recent_trades`.

- `trade_view=INCLUDED` (default): exact exclusions removed **before** pagination.
- `trade_view=EXCLUDED`: archived evidence only, with correct counts/pages.
- `trade_view=ALL`: complete preserved main-account position history.

No GET activates an account, posts a refund, inserts an exclusion event, creates
an equity observation or changes a position state. An inconsistent approved scope
fails closed to unchanged account reporting and an explicit review warning.

This patch requires no migration, no production settings change and no additional
write-off operation. Publish/deploy separately after review; do not rerun the old
write-off application script.
