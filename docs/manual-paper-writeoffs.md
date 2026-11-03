# Explicit manual paper write-offs

The user approved three specific expired main-account positions as $0-proceeds
**assumptions**, totaling $179.50 in original costs. This approval does not cover
any future missing exit, another account, or a different amount.

## Accounting

- `MANUAL_WRITE_OFF` events record negative original entry cost as realized
  modeled loss. Cash, unsettled proceeds and closing fees all change by **zero**:
  the debit (including entry fees) already happened at entry.
- Position projection becomes `WRITTEN_OFF`, not `CLOSED` or `UNSETTLED`.
- Original position detail remains intact, with an additional adjustment object.
  The immutable event also stores a full copy and hash of the original detail.
- No sale price, exit quote, actual sale timestamp, worthless-expiry proof,
  exercise outcome or settlement credit is manufactured.
- Original cash events, saved quotes, underlying R, frozen study code, policies,
  other accounts and old equity observations are not changed.
- New observations can use zero assumed value from the adjustment time onward.
  Earlier null observations stay null. Further missing prices still block totals.

The report separates completed quoted-trade P/L from write-off-adjusted P/L.
Account and trade labels explicitly identify the assumptions. Readiness continues
to warn that actual exits remain unverified; the graph is not proof of a fully
verified return. No API GET or scanner run can create these adjustments.

## After-hours application plan

1. Review and deploy the tested UI + service together; keep paper-only mode.
   There is no database migration and no automatic adjustment at startup.
2. Take an integrity-checked backup before any ledger write. Preserve the receipt.
3. Generate a read-only request with the exact three approved contract symbols,
   explicit approval reference and `--expected-total-cents 17950`:

   ```sh
   python -m app.services.paper_writeoffs plan \
     --symbol EXACT_APPROVED_CONTRACT_1 \
     --symbol EXACT_APPROVED_CONTRACT_2 \
     --symbol EXACT_APPROVED_CONTRACT_3 \
     --expected-total-cents 17950 \
     --approval-ref USER_APPROVAL_REFERENCE
   ```

   Save the resulting bounded JSON in an operator-owned private file, not Git.
   The request binds exact position IDs, symbols, costs and original-detail hashes.
4. Review that request, then apply through the operator CLI in one transaction:

   ```sh
   python -m app.services.paper_writeoffs apply --request /private/request.json
   ```

   Any changed position, mismatched total, prior real sale, incomplete retry,
   not-yet-ended contract, wrong account or conflicting authorization aborts the
   entire batch. An identical retry cannot double-book the loss.
5. Verify three adjustment events, $179.50 loss, $0 cash delta, unchanged original
   records, unchanged frozen-study fingerprint, and clear labels on the live UI.
   A new valid quote may still be needed to value any remaining open positions.

Do not run this command blindly on a new list. New missing exits require their
own investigation and explicit approval. A later verified recovery needs a
separate reviewed compensating adjustment, not deletion of the original write-off.
