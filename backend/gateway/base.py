from datetime import datetime
from typing import Protocol

from backend.domain.contracts import OrderSnapshot, PaymentSnapshot, SubscriptionSnapshot


class GatewayAdapter(Protocol):
    """Only verified gateway behavior belongs in a production adapter."""

    def get_payment(self, payment_id: str) -> PaymentSnapshot: ...
    def get_order(self, order_id: str) -> OrderSnapshot: ...
    def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot: ...

    def charge_mandate(
        self, subscription_id: str, amount_paise: int, idempotency_key: str
    ) -> PaymentSnapshot: ...

    def list_stale_orders(self, before: datetime) -> list[OrderSnapshot]: ...

    def create_payment_link(
        self, case_id: str, amount_paise: int, expires_at: datetime, idempotency_key: str
    ) -> dict[str, object]: ...
