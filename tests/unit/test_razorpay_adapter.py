from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.db.models import RecoveryAction
from backend.domain.contracts import NormalizedEvent, OrderSnapshot, PaymentSnapshot
from backend.domain.enums import (
    ActionType,
    CaseState,
    FailureCategory,
    OrderStatus,
    PaymentAttemptStatus,
)
from backend.gateway.razorpay_adapter import NotVerifiedGatewayOperation, RazorpayAdapter
from backend.orchestration.orchestrator import Orchestrator
from backend.policy.config_loader import load


class FakeResponse:
    def __init__(self) -> None:
        self.payload = {"id": "plink_test", "short_url": "https://rzp.io/i/test"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeClient:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        assert url == "https://example.test/v1/payment_links"
        self.payload = kwargs.get("json")  # type: ignore[assignment]
        return FakeResponse()


class FakeOrderClient:
    def get(self, url: str, **kwargs: object) -> FakeResponse:
        assert url == "https://example.test/v1/orders"
        assert kwargs["params"] == {"count": 100, "skip": 0, "to": 1767312000}
        response = FakeResponse()
        response.payload = {
            "items": [
                {
                    "id": "order_stale",
                    "amount": 99900,
                    "currency": "INR",
                    "status": "attempted",
                    "customer_id": "customer-stale",
                    "created_at": 1767308400,
                },
                {
                    "id": "order-paid",
                    "amount": 99900,
                    "currency": "INR",
                    "status": "paid",
                    "customer_id": "customer-paid",
                    "created_at": 1767308400,
                },
            ]
        }
        return response


def test_verified_payment_link_payload_uses_paise_and_safe_notifications() -> None:
    client = FakeClient()
    adapter = RazorpayAdapter("key", "secret", "https://example.test", client)  # type: ignore[arg-type]
    result = adapter.create_payment_link(
        "case_123",
        99900,
        datetime(2026, 1, 2, tzinfo=UTC),
        "internal-idempotency-key",
    )
    assert result["id"] == "plink_test"
    assert client.payload == {
        "amount": 99900,
        "currency": "INR",
        "reference_id": "case_123",
        "expire_by": int(datetime(2026, 1, 2, tzinfo=UTC).timestamp()),
        "notify": {"email": False, "sms": False},
        "reminder_enable": False,
    }


def test_payment_link_rejects_float_or_negative_money_before_gateway_call() -> None:
    client = FakeClient()
    adapter = RazorpayAdapter("key", "secret", "https://example.test", client)  # type: ignore[arg-type]
    expires_at = datetime(2026, 1, 2, tzinfo=UTC)
    with pytest.raises(TypeError, match="integer number of paise"):
        adapter.create_payment_link("case_float", 999.5, expires_at, "key")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        adapter.create_payment_link("case_negative", -1, expires_at, "key")
    assert client.payload is None


def test_unverified_real_operations_fail_closed() -> None:
    adapter = RazorpayAdapter("key", "secret", "https://example.test", FakeClient())  # type: ignore[arg-type]
    with pytest.raises(NotVerifiedGatewayOperation):
        adapter.charge_mandate("sub", 100, "key")
    with pytest.raises(NotVerifiedGatewayOperation):
        adapter.list_stale_orders(datetime.now(UTC) - timedelta(hours=1))


def test_verified_order_sweeper_filters_paid_and_recent_orders(monkeypatch) -> None:
    monkeypatch.setenv("RAZORPAY_ENABLE_ORDER_SWEEPER", "true")
    adapter = RazorpayAdapter("key", "secret", "https://example.test", FakeOrderClient())  # type: ignore[arg-type]
    orders = adapter.list_stale_orders(datetime(2026, 1, 2, tzinfo=UTC))
    assert [order.order_id for order in orders] == ["order_stale"]
    assert orders[0].status.value == "ATTEMPTED"


def test_real_adapter_path_creates_link_and_waits_for_captured_webhook() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    now = datetime(2026, 1, 1, 4, tzinfo=UTC)
    order = OrderSnapshot("order-real", 99900, "INR", OrderStatus.ATTEMPTED, "customer-real", now)
    event = NormalizedEvent(
        "event-real",
        "payment.failed",
        now,
        "merchant-real",
        "customer-real",
        order_id=order.order_id,
        payment=PaymentSnapshot(
            "payment-real",
            99900,
            PaymentAttemptStatus.FAILED,
            "upi",
            "bank",
            order.order_id,
            error_code=FailureCategory.INSUFFICIENT_FUNDS.value,
        ),
        order=order,
    )
    gateway = RazorpayAdapter("key", "secret", "https://example.test", FakeClient())  # type: ignore[arg-type]
    orchestrator = Orchestrator(session, gateway, load())
    case = orchestrator.ingest(event)
    assert case is not None
    result = orchestrator.process(
        case,
        now=now,
        auto_approve=True,
        candidate_action=ActionType.CREATE_PAYMENT_LINK,
        execute_immediately=True,
    )
    assert result.state is CaseState.DECIDED
    assert result.recovered is False
    action = session.get(RecoveryAction, result.action_id)
    assert action is not None
    assert action.result["payment_link"]["id"] == "plink_test"
