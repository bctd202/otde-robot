"""Frozen draft evaluation helpers. No data collection or performance claims."""
from datetime import date, datetime, timedelta
import math
import random

from app.services.market_calendar import HOLIDAYS_BY_YEAR, NY, is_market_day, market_close
from app.services.retest_research import stamp

SESSIONS = 60
BLOCK = 5
REPLICATES = 10_000
SEED = 20261027
METHOD = "paired-overlapping-noncircular-five-session-blocks-v1"


def evaluation_sessions(activated_at: datetime) -> tuple[date, ...]:
    """Include a partial actual activation session, never extend for outages.

    Pre-open activation starts that exchange day; after-close activation starts
    next exchange day. Unknown calendar years fail closed, not guessed weekdays.
    """
    local = stamp(activated_at).astimezone(NY)
    day = local.date()
    if local.time() >= market_close(day):
        day += timedelta(days=1)
    days: list[date] = []
    while len(days) < SESSIONS:
        if day.year not in HOLIDAYS_BY_YEAR:
            raise ValueError("Calendar must be reviewed before freezing this experiment")
        if is_market_day(day):
            days.append(day)
        day += timedelta(days=1)
    return tuple(days)


def paired_block_bootstrap(control: list[float | None], treatment: list[float | None]) -> dict:
    """Paired daily liquidation-equity changes in dollars, same frozen 60 sessions.

    True zero-trade days are included. An outage/unknown valuation is None, never
    imputed zero. Resample both arms using identical starts, twelve consecutive
    five-session blocks drawn from the 56 overlapping noncircular blocks. Report
    the 2.5/97.5 percentile interval of treatment-minus-control total net dollars.
    This interval is uncertainty evidence, not a stand-alone pass/fail gate.
    """
    if len(control) != SESSIONS or len(treatment) != SESSIONS:
        raise ValueError("Exactly 60 aligned sessions required, including zero-trade days")
    values = control+treatment
    if any(value is None or not math.isfinite(value) for value in values):
        return {"status": "INCONCLUSIVE", "reason": "Unresolved exposure or valuation gaps",
                "method": METHOD}
    differences = [float(t)-float(c) for c, t in zip(control, treatment)
                   if c is not None and t is not None]
    generator = random.Random(SEED)
    blocks = [sum(differences[i:i+BLOCK]) for i in range(SESSIONS-BLOCK+1)]
    totals = sorted(sum(generator.choice(blocks) for _ in range(SESSIONS//BLOCK))
                    for _ in range(REPLICATES))

    def percentile(p: float) -> float:
        position = (REPLICATES-1)*p
        lower = math.floor(position)
        upper = math.ceil(position)
        return totals[lower]+(totals[upper]-totals[lower])*(position-lower)

    return {"status": "ESTIMATED", "method": METHOD, "seed": SEED,
            "replicates": REPLICATES, "block_sessions": BLOCK, "sessions": SESSIONS,
            "advantage_dollars": sum(differences),
            "percentile_95_dollars": [percentile(.025), percentile(.975)]}
