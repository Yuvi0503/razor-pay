"""Out-of-band raw-event worker; webhook acknowledgement does not run this work."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import RawEvent
from backend.domain.contracts import NormalizedEvent
from backend.gateway.base import GatewayAdapter
from backend.orchestration.orchestrator import Orchestrator
from backend.policy.config_loader import PolicyConfig

from .normalizer import normalize


def process_pending(
    session: Session,
    gateway: GatewayAdapter,
    policy: PolicyConfig,
    *,
    execute_actions: bool = False,
    batch_size: int = 100,
) -> int:
    """Normalize pending events and optionally execute their first safe action.

    The webhook request only stores the raw event. This worker owns later
    normalization, policy evaluation, scheduling, and optional demo execution.
    """
    count = 0
    statement = (
        select(RawEvent)
        .where(RawEvent.processed_at.is_(None))
        .order_by(RawEvent.received_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    for raw in session.scalars(statement):
        if not isinstance(raw.payload, dict):
            raw.processed_at = raw.received_at
            continue
        event: NormalizedEvent = normalize(raw.provider_event_id, raw.payload, raw.received_at)
        orchestrator = Orchestrator(session, gateway, policy)
        case = orchestrator.ingest(event)
        if execute_actions and case is not None and case.state.value == "OPEN":
            orchestrator.process(case, execute_immediately=True)
        raw.processed_at = raw.received_at
        count += 1
    session.commit()
    return count


__all__ = ["process_pending"]
