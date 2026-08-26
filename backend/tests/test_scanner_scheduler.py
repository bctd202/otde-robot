from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.main import SCANNER_JOB_ID, add_scanner_job

NY = ZoneInfo("America/New_York")


def test_scanner_job_is_minute_aligned_and_runs_once_per_minute():
    scheduler = BackgroundScheduler(timezone=NY)
    job = add_scanner_job(scheduler, lambda: None)
    assert job.id == SCANNER_JOB_ID
    assert isinstance(job.trigger, CronTrigger)
    first = job.trigger.get_next_fire_time(None, datetime(2026, 8, 26, 10, 0, 6, tzinfo=NY))
    second = job.trigger.get_next_fire_time(first, first)
    assert first == datetime(2026, 8, 26, 10, 1, 5, tzinfo=NY)
    assert second == datetime(2026, 8, 26, 10, 2, 5, tzinfo=NY)


def test_scanner_job_prevents_overlap_and_coalesces_missed_runs():
    scheduler = BackgroundScheduler(timezone=NY)
    job = add_scanner_job(scheduler, lambda: None)
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 30
