from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from ..models import RawEvent


class RawEventRepository:
    """Persistence operations for verified provider events.

    Methods only stage work in the caller's transaction. The caller owns commit and
    rollback so webhook acknowledgement and downstream work can share a boundary.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def insert_if_new(
        self,
        *,
        provider_event_id: str,
        event_type: str | None,
        payload: Mapping[str, object] | list[object],
        received_at: datetime | None = None,
    ) -> bool:
        values: dict[str, Any] = {
            "provider_event_id": provider_event_id,
            "event_type": event_type,
            "signature_valid": True,
            "payload": payload,
        }
        if received_at is not None:
            values["received_at"] = received_at
            values["created_at"] = received_at

        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as postgres_insert

            statement: Any = postgres_insert(RawEvent).values(**values).on_conflict_do_nothing(
                index_elements=[RawEvent.provider_event_id]
            )
        else:
            statement = insert(RawEvent).values(**values).prefix_with("OR IGNORE")

        result = self.session.execute(statement)
        rowcount = getattr(result, "rowcount", None)
        return isinstance(rowcount, int) and rowcount == 1
