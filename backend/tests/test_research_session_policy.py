from datetime import date
import pytest
from app.services.market_calendar import NY
from app.services.research_session_policy import session_limits


@pytest.mark.parametrize("day,hour", [(date(2026,10,27),15), (date(2026,11,27),12),
                                     (date(2026,12,24),12), (date(2027,3,15),15)])
def test_versioned_cutoff_follows_close_and_dst(day,hour):
    limits=session_limits(day)
    assert limits['entry_cutoff'].astimezone(NY).hour==hour
    assert limits['entry_cutoff'].astimezone(NY).minute==45
    assert limits['timed_exit_candle']==limits['entry_cutoff']


@pytest.mark.parametrize("day",[date(2026,11,26),date(2026,10,31),date(2029,1,2)])
def test_closed_and_unconfigured_dates_fail_closed(day):
    with pytest.raises(ValueError):session_limits(day)
