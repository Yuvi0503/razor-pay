from datetime import datetime
from typing import Protocol


class GatewayAdapter(Protocol):
    """Only verified gateway behavior belongs in a production adapter."""

    def get_payment(self, payment_id: str) -> dict: ...
    def get_order(self, order_id: str) -> dict: ...
    def create_payment_link(
        self, case_id: str, amount_paise: int, expires_at: datetime, idempotency_key: str
    ) -> dict: ...
