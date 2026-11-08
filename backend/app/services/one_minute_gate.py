"""One deterministic BUY decision for live scans and evidenced historical replay."""
from dataclasses import dataclass
from typing import Literal

from app.services.indicators import spread_pct


@dataclass(frozen=True)
class GateResult:
    score: float
    signal: Literal["BUY", "WATCH", "MISSED", "PASS"]
    entry_low: float
    entry_high: float
    no_chase: float


def evaluate(setup, contract) -> GateResult:
    midpoint = round((contract.bid+contract.ask)/2, 2)
    preferred = min(midpoint, contract.last) if contract.last > 0 else midpoint
    low = round(preferred, 2)
    high = round(min(1.0, preferred*1.08), 2)
    ceiling = round(min(1.25, max(high+.05, preferred*1.25)), 2)
    score = max(0, min(100, 42+setup.checks*8+min(contract.volume/250, 8)
                       +min(contract.open_interest/1000, 4)-spread_pct(contract.bid, contract.ask)/4))
    signal: Literal["BUY", "WATCH", "MISSED", "PASS"]
    if setup.confirmed and (contract.ask > ceiling or setup.extension_r > 1.35):
        signal = "MISSED"
    elif score >= 85 and setup.confirmed and contract.ask <= high and setup.extension_r <= 1.35:
        signal = "BUY"
    elif score >= 70:
        signal = "WATCH"
    else:
        signal = "PASS"
    return GateResult(score, signal, low, high, ceiling)
