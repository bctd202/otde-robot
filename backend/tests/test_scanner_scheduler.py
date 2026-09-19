from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from app.main import SCANNER_JOB_ID, MarketHoursTrigger, add_scanner_job

NY = ZoneInfo("America/New_York")


def test_scanner_job_is_minute_aligned_during_regular_market_hours():
    scheduler = BackgroundScheduler(timezone=NY)
    job = add_scanner_job(scheduler, lambda: None)
    assert job.id == SCANNER_JOB_ID
    assert isinstance(job.trigger, MarketHoursTrigger)
    first = job.trigger.get_next_fire_time(None, datetime(2026, 8, 26, 10, 0, 6, tzinfo=NY))
    second = job.trigger.get_next_fire_time(first, first)
    assert first == datetime(2026, 8, 26, 10, 1, 5, tzinfo=NY)
    assert second == datetime(2026, 8, 26, 10, 2, 5, tzinfo=NY)


def test_scanner_job_runs_close_housekeeping_then_sleeps_for_weekend():
    scheduler = BackgroundScheduler(timezone=NY)
    job = add_scanner_job(scheduler, lambda: None)
    close_run = job.trigger.get_next_fire_time(
        None, datetime(2026, 9, 18, 15, 59, 6, tzinfo=NY)
    )
    monday_open = job.trigger.get_next_fire_time(close_run, close_run)
    assert close_run == datetime(2026, 9, 18, 16, 0, 5, tzinfo=NY)
    assert monday_open == datetime(2026, 9, 21, 9, 30, 5, tzinfo=NY)


def test_scanner_job_skips_holiday_and_honors_early_close():
    scheduler = BackgroundScheduler(timezone=NY)
    job = add_scanner_job(scheduler, lambda: None)
    after_labor_day_open = job.trigger.get_next_fire_time(
        None, datetime(2026, 9, 4, 16, 0, 6, tzinfo=NY)
    )
    thanksgiving_cleanup = job.trigger.get_next_fire_time(
        None, datetime(2026, 11, 27, 12, 59, 6, tzinfo=NY)
    )
    assert after_labor_day_open == datetime(2026, 9, 8, 9, 30, 5, tzinfo=NY)
    assert thanksgiving_cleanup == datetime(2026, 11, 27, 13, 0, 5, tzinfo=NY)


def test_scanner_job_uses_published_2028_new_year_and_july_calendar():
    scheduler = BackgroundScheduler(timezone=NY)
    job = add_scanner_job(scheduler, lambda: None)
    saturday_new_year = job.trigger.get_next_fire_time(
        None, datetime(2027, 12, 31, 16, 0, 6, tzinfo=NY)
    )
    july_cleanup = job.trigger.get_next_fire_time(
        None, datetime(2028, 7, 3, 12, 59, 30, tzinfo=NY)
    )
    assert saturday_new_year == datetime(2028, 1, 3, 9, 30, 5, tzinfo=NY)
    assert july_cleanup == datetime(2028, 7, 3, 13, 0, 5, tzinfo=NY)


def test_scanner_job_prevents_overlap_and_coalesces_missed_runs():
    scheduler = BackgroundScheduler(timezone=NY)
    job = add_scanner_job(scheduler, lambda: None)
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 30
