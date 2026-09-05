"""Durable scheduler entry points shared by the API and background worker."""

from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from backend.db.engine import database_url, session_factory
from backend.db.models import RecoveryAction
from backend.domain.enums import RecoveryActionState
from backend.gateway.razorpay_adapter import RazorpayAdapter
from backend.orchestration.orchestrator import Orchestrator
from backend.policy.config_loader import load
from backend.scheduler import build_scheduler, schedule_action


def execute_scheduled_action(action_id: str) -> None:
    """Execute one persisted action in an isolated database transaction."""
    session = session_factory()()
    try:
        Orchestrator(session, RazorpayAdapter(), load()).execute_action(action_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def sync_scheduled_actions(now: datetime | None = None) -> int:
    """Ensure every durable scheduled action has its APScheduler job.

    Webhook processing and approvals only persist an action.  This reconciler
    makes the scheduler resilient to restarts and to actions created by another
    process without relying on in-memory hand-off.
    """
    session = session_factory()()
    scheduler = build_scheduler(database_url(), execute_scheduled_action)
    scheduler.start(paused=True)
    try:
        statement = select(RecoveryAction).where(
            RecoveryAction.state == RecoveryActionState.SCHEDULED
        )
        actions = list(session.scalars(statement))
        for action in actions:
            job_id = f"recovery-action:{action.id}"
            if scheduler.get_job(job_id) is None:
                schedule_action(scheduler, action.id, action.scheduled_for)
        return len(actions)
    finally:
        scheduler.shutdown(wait=False)
        session.close()


def build_runtime_scheduler() -> BackgroundScheduler:
    """Build the singleton scheduler used by the API process."""
    return build_scheduler(database_url(), execute_scheduled_action)


def utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "build_runtime_scheduler",
    "execute_scheduled_action",
    "sync_scheduled_actions",
    "utcnow",
]
