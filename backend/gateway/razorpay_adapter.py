import os
from datetime import UTC, datetime

import httpx

from backend.domain.contracts import OrderSnapshot, PaymentSnapshot, SubscriptionSnapshot
from backend.domain.enums import OrderStatus
from backend.domain.money import require_paise


class NotVerifiedGatewayOperation(RuntimeError):
    pass


class RazorpayAdapter:
    """Razorpay Test Mode adapter with fail-closed unverified operations."""

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.key_id = key_id if key_id is not None else os.getenv("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret if key_secret is not None else os.getenv("RAZORPAY_KEY_SECRET", "")
        configured_base_url = (
            base_url
            if base_url is not None
            else os.getenv("RAZORPAY_BASE_URL", "https://api.razorpay.com")
        )
        self.base_url = configured_base_url.rstrip("/")
        self.client = client or httpx.Client(auth=(self.key_id, self.key_secret), timeout=8.0)

    def _require_credentials(self) -> None:
        if not self.key_id or not self.key_secret:
            raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required")

    def charge_mandate(self, *_: object, **__: object) -> PaymentSnapshot:
        raise NotVerifiedGatewayOperation(
            "A1/A2/A3/A7 are not verified; mandate charging is disabled"
        )

    def list_stale_orders(self, *_: object, **__: object) -> list[OrderSnapshot]:
        before = _[0] if _ and isinstance(_[0], datetime) else __.get("before")
        if not isinstance(before, datetime):
            raise TypeError("before must be a datetime")
        if os.getenv("RAZORPAY_ENABLE_ORDER_SWEEPER", "false").lower() != "true":
            raise NotVerifiedGatewayOperation("A4 is feature-gated; order sweeping is disabled")
        self._require_credentials()
        output: list[OrderSnapshot] = []
        skip = 0
        while skip < 1000:
            response = self.client.get(
                f"{self.base_url}/v1/orders",
                params={"count": 100, "skip": skip, "to": int(before.astimezone(UTC).timestamp())},
            )
            response.raise_for_status()
            body = response.json()
            items = body.get("items") if isinstance(body, dict) else None
            if not isinstance(items, list):
                raise TypeError("Razorpay orders response did not contain items")
            for item in items:
                snapshot = self._order_snapshot(item, before)
                if snapshot is not None:
                    output.append(snapshot)
            if len(items) < 100:
                break
            skip += len(items)
        return output

    @staticmethod
    def _order_snapshot(item: object, before: datetime) -> OrderSnapshot | None:
        if not isinstance(item, dict):
            return None
        provider_order_id = item.get("id")
        customer_id = item.get("customer_id")
        notes = item.get("notes")
        if not isinstance(customer_id, str) and isinstance(notes, dict):
            customer_id = notes.get("customer_id")
        created_at = item.get("created_at")
        status = item.get("status")
        if not isinstance(provider_order_id, str) or not isinstance(customer_id, str):
            return None
        if not isinstance(created_at, (int, float)) or not isinstance(status, str):
            return None
        created = datetime.fromtimestamp(created_at, tz=UTC)
        if created >= before or status.lower() == "paid":
            return None
        status_map = {"created": OrderStatus.CREATED, "attempted": OrderStatus.ATTEMPTED}
        normalized_status = status_map.get(status.lower())
        if normalized_status is None:
            return None
        amount = item.get("amount")
        currency = item.get("currency", "INR")
        if not isinstance(amount, int) or not isinstance(currency, str):
            return None
        return OrderSnapshot(
            order_id=provider_order_id,
            amount_paise=amount,
            currency=currency,
            status=normalized_status,
            customer_id=customer_id,
            created_at=created,
        )

    def create_payment_link(
        self, case_id: str, amount_paise: int, expires_at: datetime, idempotency_key: str
    ) -> dict[str, object]:
        require_paise(amount_paise)
        self._require_credentials()
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "reference_id": case_id[:40],
            "expire_by": int(expires_at.astimezone(UTC).timestamp()),
            "notify": {"email": False, "sms": False},
            "reminder_enable": False,
        }
        response = self.client.post(f"{self.base_url}/v1/payment_links", json=payload)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not body.get("id") or not body.get("short_url"):
            raise RuntimeError("Razorpay payment-link response did not contain id and short_url")
        return body

    def get_payment(self, payment_id: str) -> PaymentSnapshot:
        raise NotVerifiedGatewayOperation("Payment read-back mapping is not verified for this project")

    def get_order(self, order_id: str) -> OrderSnapshot:
        raise NotVerifiedGatewayOperation("Order read-back mapping is not verified for this project")

    def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        raise NotVerifiedGatewayOperation("Subscription read-back mapping is not verified for this project")
