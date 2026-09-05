"""Persistent action scheduling backed by APScheduler's SQL job store."""

from collections.abc import Callable
from datetime import datetime

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler


def build_scheduler(database_url: str, handler: Callable[[str], None]) -> BackgroundScheduler:
    """Create a restart-safe scheduler; jobs are keyed by recovery-action ID."""
    scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=database_url)},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 15 * 60},
        timezone="UTC",
    )
    scheduler._recovery_handler = handler
    return scheduler


def schedule_action(
    scheduler: BackgroundScheduler, action_id: str, run_at: datetime
) -> None:
    handler = scheduler._recovery_handler
    scheduler.add_job(
        handler,
        "date",
        run_date=run_at,
        args=[action_id],
        id=f"recovery-action:{action_id}",
        replace_existing=True,
        misfire_grace_time=15 * 60,
    )


__all__ = ["build_scheduler", "schedule_action"]
