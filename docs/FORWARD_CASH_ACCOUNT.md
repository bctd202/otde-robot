# Forward simulated cash account (v1)

> Historical v1 specification. The October 19 corrected trial supersedes v1 as
> the active account. V1 remains read-only with its original balances, policy,
> and unresolved positions. See [trial isolation and archive procedure](CORRECTED_TRIAL.md).

This is a constrained **simulation**, not brokerage paper fills or live trading.
Quoted prices do not guarantee execution. No order endpoint is called.

## Start and isolation

After migration `0014_forward_paper_account`, scanner startup creates one durable
`forward-cash-v1` account. Its starting capital is `PAPER_MONEY_STARTING_CASH`
(default $2,000). The balance and policy are frozen at creation: restarting or
changing that environment setting does not reset or restate the account.
The startup entry-mark watermark excludes all existing history. A new account
never imports old positions, dollars, option marks, or R. The GET endpoint
`/api/forward-paper-account?page=1` is read-only and does not activate an account.

Both automated engines share this account. Existing first-ticker/day automated
ENTRY marks define eligibility; the account does not change selection. Lotto
and manually entered positions remain entirely separate. Historical replay
sliders and strategy filters do not change the forward account.

## Frozen v1 assumptions

- One standard, 100-share-multiplier contract per accepted entry.
- Maximum three simultaneous positions, including unresolved missing-price exits.
- Maximum $100 entry debit **including** the closing-cost reserve.
- Fill at a later observed, exact-contract live ask plus $0.01 premium per share.
- Exit at an observed live bid minus $0.01 premium per share, floored at zero.
- $1 opening commission, $0 closing commission; **assumed** $0.50 additional fee
  allowance on each side. The allowance is not an exact regulatory/exchange invoice.
- Both bid and ask must be finite, correctly identified, no more than 60 seconds
  old, not future-dated, and at least one second after the entry/exit decision.
  Entry spread must be at most 20% of ask; entry bid must be positive.
- Entry deadline: 120 seconds after saved entry evidence. No catching up on old
  trades after an outage. Actual fill latency is the next available scanner
  observation, often about a minute, **not** guaranteed one-second execution.
- Exits follow the **unchanged underlying stop/target/time decisions** when the
  scanner learns of them. They are not option-premium stops and not intrabar
  executions at the ideal barrier price. A later quote is required, within both
  180 seconds of the underlying exit timestamp and 180 seconds of the request.
- Ledger quotes are read from the scanner cache. Before processing, a bounded
  refresher keeps held/pending contracts observable even after a setup disappears:
  at most six chain refreshes per scan, held/older exposure first. Do not initiate
  another refresh when the reported remaining budget is 20 requests or less;
  adapters still enforce their own per-request limits. No refreshes off-hours,
  on unhealthy feeds, or from GET.
  There is no retrospective quote lookup. Missing quotes mean missed simulated
  entries or unresolved exits, not synthetic prices.

Opening commission aligns with tastytrade's published stock/ETF-option schedule,
checked 2026-10-12: [tastytrade pricing](https://tastytrade.com/pricing/).
Fees and slippage are intentionally explicit modeling assumptions; they are not
claimed to bound every real trading cost.

## Cash and settlement

All ledger money is integer USD cents. Entry deducts premium plus opening costs
from settled cash. Closing costs are reserved so even an explicitly observed
zero bid can close without borrowing. An exit charges those reserved closing
costs to settled cash and places gross sale proceeds in unsettled cash.

The simulated cash account makes proceeds available at 09:30 ET on the next day
that is both an exchange business day and a banking business day, when processed
by the scanner. This is a conservative posting assumption, not a promise about
a broker's exact posting hour. No reuse of unsettled proceeds or margin.
Columbus Day and Veterans Day are excluded in addition to exchange holidays;
see the [OCC 2026 holiday schedule](https://infomemo.theocc.com/infomemos?number=57897).
The implementation supports the configured 2026–2028 calendar; unknown future
years leave proceeds unsettled pending a calendar update rather than guessing.

## Honest unknowns and P/L

- Net realized P/L = sale proceeds − closing costs − original entry debit.
- Settled cash and unsettled cash are **not** profit.
- Available buying power = settled cash − reserved closing costs.
- Estimated liquidation equity = settled + unsettled + fresh net bid liquidation
  estimates. It is `null` if **any** held exposure cannot be freshly priced.
- Missing exits, expired windows, session-end outages, and underlying data gaps
  create `UNPRICED` exposure. They do not manufacture a sale, loss, or cash refund.
- An unresolved exit continues consuming cash and a concurrency slot. There is
  deliberately no automatic write-off or reset. Resolution requires a future
  explicitly audited reconciliation feature, not silent historical edits.
- Costs charged so far include open-position entry costs; realized P/L only
  contains costs for completed trades. The UI separates these amounts.
- No exercise, assignment, queue position, partial fills or broker reconciliation
  are simulated. Even a fresh bid/ask is not a guaranteed executable fill.

## Audit and deployment

Three new tables contain the account, position projection, and append-only
event ledger. Unique account/event and account/signal keys prevent duplicate
funding, entries, exits and settlements. Position state and money events commit
atomically; a database writer lock serializes account updates. Original signals,
R, manual positions, lotto records and automated shadow marks are untouched.

The dashboard leads with this account, then retains historical signal research
and explicitly labels the old cash replay as a before-cost what-if. The new
graphs distinguish cumulative realized P/L from cash held. The paginated ledger
stores exact quote timestamps, contract/provider, price assumptions, and entry
plans. Missing values are never plotted as invented total-account returns.

Deploy only with migrations and the normal paper-only scanner configuration.
Activation begins **on deployment/startup**, not on the dates in old reports.
Verify funding appears exactly once, no old positions were imported, and the
scanner stays healthy. Do not call a profitable closed subset a profitable
account while unpriced exposure remains.
