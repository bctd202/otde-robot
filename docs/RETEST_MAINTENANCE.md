# Resume the existing breakout/retest comparison after feed maintenance

The operator requested continuing the existing test, accounts and Tastytrade
feed. Do not create another run, account, start date, funding deposit or replay.

The October 30 transport repair changed only `market_data/tastytrade.py` and
`market_data/cached.py` within the original fingerprint. The frozen strategy
files and configured settings were unchanged. This repair adds a shared admission
check and an explicit, append-only `MAINTENANCE_RESUME` event for the reviewed
deployed fingerprint. It does not overwrite the original policy or spec hash.
Both control and treatment resume together on future real observations. Existing
skips, trades, observations, costs, balances and 60-session dates remain intact.

No GET, startup or scan creates the acknowledgment. Future code/configuration
changes block again; this is not a general exception or automatic approval.
Reads distinguish a current block from past protocol interruptions. The original
uninterrupted-protocol verdict remains inconclusive after maintenance, while
observed results and new prospective trades continue to be displayed.

November 4 is an outage day with missing observations, not a loss, a zero-return
session or a candidate for backfilled paper fills. Keep the missing input and
valuation evidence; do not use it to judge strategy success or replay skipped
orders. The fixed window is not silently extended or relabeled as complete.

After hours, validate the diff and all required checks, take a verified database
backup, deploy the exact reviewed revision, and run inside the backend container:

```sh
python -m app.services.retest_maintenance \
  --revision REVIEWED_FULL_GIT_SHA \
  --expected-code-hash REVIEWED_DEPLOYED_CODE_HASH \
  --expected-frozen-hash ORIGINAL_RUN_CODE_HASH \
  --confirm RESUME-EXISTING-PAPER-TEST
```

This verifies the original policy digest, unchanged paper settings, complete
existing funding, exact current/original fingerprints and after-hours chronology.
It appends one zero-cash event. Repeating it is a no-op. Verify no policy, cash,
account or historical position changes, confirm the admission block is cleared
in readiness and the research API, and confirm both arms still use their saved
entry chronology and quote checks. No database migration is needed.
