# Ten-position paper account — prepared, not activated

## What changes

`tasty-capacity-ten-v1` is an independent $2,000 simulated account shared by
One-Minute and Structured Intraday. It allows ten held positions instead of
three. It does not share cash or slots with lotto, the old main account, or any
breakout/retest comparison arm. Overlapping trades across accounts are separate
experiments, not additive portfolio profits.

It inherits the reviewed main account policy except for identity, label,
activation metadata and capacity. Quantity remains one contract. The main
account's $100 all-in entry ceiling (including closing reserve), later quotes,
spread checks, fees, slippage, deadlines, baseline exits and settlement rules
stay unchanged. This is not the lotto premium-only ceiling. No live orders.

The ledger records eligible post-activation entry marks even when the account
must skip them. Capacity skips are not fills and are not backfilled after space
opens. Signal selection and one-ticker/day rules are unchanged. The separate
retest opportunity view already ignores cash/slot constraints, but still applies
its first-opportunity, verification and quote rules; it is not a funded portfolio.

## Preserved evidence and limitations

- Original accounts, funding events, unknown exits and balances are untouched.
- Missing exits still consume slots and capital. A bigger account does **not**
  repair quote failures or guarantee ten fills. No fabricated expiry proceeds.
- Opening the dashboard, scanner startup and restarting cannot activate/reset it.
- Activation captures the current entry-mark watermark: no historical imports.
- Ten positions can amplify correlated exposure; capacity is not a profitability
  improvement. Settled cash can constrain fills before all slots are used.
- Shared quote work services baseline and frozen retest first. Expanded-account
  refreshes then use existing cache and at most six extra chain requests, retaining
  the existing 20-request reserve. Coverage can still be incomplete.
- The new dashboard labels full/blocked accounts, used/free slots and unknown
  exits, and links to uncapped research. A stale response is not current capacity.

## Why a separate writer

The active retest study fingerprints `forward_account.py`, including its read
helpers. Refactoring that file would stop admissions and mark protocol drift.
`expanded_account.py` deliberately forks its a99fe8e writer and summary, sharing
unchanged quote/valuation helpers where account identity is already explicit.
No frozen-source file or retest policy changes. Do not casually consolidate these
writers until the existing study ends; independently test future fixes in both.

## After-hours release / activation checklist

This change prepares code only. No production activation or migration has been
performed as part of implementation. Existing tables suffice; no schema change.

1. Review diff; pass full backend/frontend checks and CI. Record reviewed commit.
2. After market close, take a consistent SQLite backup and record old account
   cash/events/positions and retest policy/source fingerprint before release.
3. Deploy the reviewed image normally, retaining environment and data volumes.
   Verify health, paper-only mode, data provider, scanner schedule and migration.
4. Confirm retest source fingerprint still equals the activated policy's hash,
   and no new protocol-drift events. New account should report `NOT_STARTED`.
5. With explicit activation approval, in one transaction call
   `expanded_account.activate(db, revision=<full deployed SHA>, now=<actual UTC>)`.
   This rejects regular-session activation and non-Tastytrade/non-paper settings.
   Retrying returns the existing account and never funds it again.
6. Verify exactly one $2,000 funding event, max_positions=10, zero imported
   positions, and old account/retest totals unchanged. Keep old unknowns unknown.
7. Next session verify later-quote entries, ten-slot accounting, saved skips,
   exits/settlement, scanner timings and request reserve. Investigate missing
   exits separately; do not loosen checks or manufacture proceeds to clear slots.

Dashboard: History → Paper trial. Research → Uncapped opportunities exposes the
independent breakout/retest observations. The ten-position account becomes the
default forward-account API view; preserved accounts remain selectable.

Trade Board → Paper accounts provides direct links to the new and original main
accounts, both multi-position lotto exits, and all four frozen comparison arms.
Each link selects its exact account and opens the existing balance/graph view.
The directory shows policy starting amounts, never invented live balances or
combined returns. Older archive versions remain in each area's account selector.
