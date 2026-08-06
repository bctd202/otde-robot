from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.market import CandleOut
from app.services.structured_intraday import evaluate_structured_setup

NY = ZoneInfo("America/New_York")


def structured_candles() -> list[CandleOut]:
    start = datetime.combine(datetime(2026, 8, 5).date(), time(9, 30), tzinfo=NY)
    rows = []
    for index in range(90):
        stamp = start + timedelta(minutes=index)
        if index < 60:
            close = 100 + index * .033
            low = close - .08
        elif index == 60:
            close, low = 100.5, 99
        elif index < 75:
            close = 100.5 + (index - 60) * .18
            low = close - .08
        else:
            close = 103 + (index - 75) * .065
            low = close - .08
        open_price = close - .04
        rows.append(CandleOut(symbol="SPY", timeframe="1m", timestamp=stamp,
            open=open_price, high=close + .08, low=low, close=close,
            volume=100_000 + index * 1000))
    return rows


def test_structured_model_requires_context_then_confirms_sweep_shift_and_two_r_plan():
    rows = structured_candles()
    early = evaluate_structured_setup(rows[:45], rows[44].close, rows[44].timestamp)
    assert early.status == "PASS"
    assert "full hour" in early.rejection_reasons[0]

    completed_at = rows[-1].timestamp
    result = evaluate_structured_setup(rows, rows[-1].close, completed_at)
    assert result.direction == "call"
    assert result.status == "BUY"
    assert any("15M" in reason and "swept" in reason for reason in result.reasons)
    assert any("5M market-structure shift" in reason for reason in result.reasons)
    assert round((result.target - result.trigger) / (result.trigger - result.stop), 2) == 2


def test_structured_model_is_deterministic_for_identical_completed_candles():
    rows = structured_candles()
    first = evaluate_structured_setup(rows, rows[-1].close, rows[-1].timestamp)
    second = evaluate_structured_setup(rows, rows[-1].close, rows[-1].timestamp)
    assert first == second
