"""Normalize the small subset of provider payloads used by recovery."""

from datetime import UTC, datetime
from typing import Any

from backend.domain.contracts import (
    NormalizedEvent,
    OrderSnapshot,
    PaymentSnapshot,
    SubscriptionSnapshot,
)
from backend.domain.enums import FailureCategory, OrderStatus, PaymentAttemptStatus
from backend.domain.failure_taxonomy import map_error


def _nested(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    value: Any = payload
    for key in keys:
        value = value.get(key, {}) if isinstance(value, dict) else {}
    return value if isinstance(value, dict) else {}


def _time(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _category(payment: dict[str, Any]) -> FailureCategory:
    explicit = payment.get("failure_category")
    if isinstance(explicit, str):
        try:
            return FailureCategory(explicit)
        except ValueError:
            pass
    error = payment.get("error", {})
    code = error.get("code") if isinstance(error, dict) else None
    return map_error(code if isinstance(code, str) else None)


def normalize(
    provider_event_id: str, payload: dict[str, Any], received_at: datetime | None = None
) -> NormalizedEvent:
    event_type = str(payload.get("event", "unknown"))
    payment = _nested(payload, "payload", "payment", "entity")
    order = _nested(payload, "payload", "order", "entity")
    subscription = _nested(payload, "payload", "subscription", "entity")
    payment_id = payment.get("id")
    order_id = payment.get("order_id") or order.get("id")
    subscription_id = payment.get("subscription_id") or subscription.get("id")
    payment_status = PaymentAttemptStatus.FAILED if event_type.endswith("failed") else PaymentAttemptStatus.CAPTURED
    payment_snapshot = None
    if isinstance(payment_id, str):
        payment_snapshot = PaymentSnapshot(
            payment_id=payment_id,
            amount_paise=int(payment.get("amount", 0)),
            status=payment_status,
            method=payment.get("method") if isinstance(payment.get("method"), str) else None,
            issuer_or_bank=(payment.get("bank") or payment.get("issuer")),
            order_id=order_id if isinstance(order_id, str) else None,
            subscription_id=subscription_id if isinstance(subscription_id, str) else None,
            error_code=_nested(payment, "error").get("code"),
            error_reason=_nested(payment, "error").get("reason"),
            captured_at=None if payment_status is PaymentAttemptStatus.FAILED else _time(payment.get("created_at")),
        )
    order_snapshot = None
    if isinstance(order_id, str):
        status = OrderStatus.PAID if event_type in {"order.paid", "payment.captured"} else OrderStatus.ATTEMPTED
        order_snapshot = OrderSnapshot(
            order_id=order_id,
            amount_paise=int(order.get("amount", payment.get("amount", 0))),
            currency=str(order.get("currency", "INR")),
            status=status,
            customer_id=str(payload.get("customer_id", order.get("customer_id", "customer"))),
            created_at=_time(order.get("created_at")) or received_at or datetime.now(UTC),
        )
    subscription_snapshot = None
    if isinstance(subscription_id, str):
        subscription_snapshot = SubscriptionSnapshot(
            subscription_id=subscription_id,
            customer_id=str(payload.get("customer_id", subscription.get("customer_id", "customer"))),
            amount_paise=int(subscription.get("amount", payment.get("amount", 0))),
            status=str(subscription.get("status", "active")),
            mandate_active=str(subscription.get("status", "active")) not in {"cancelled", "halted"},
            next_charge_at=_time(subscription.get("charge_at")),
        )
    return NormalizedEvent(
        provider_event_id=provider_event_id,
        event_type=event_type,
        received_at=received_at or datetime.now(UTC),
        merchant_id=str(payload.get("merchant_id", "merchant")),
        customer_id=str(payload.get("customer_id", (order_snapshot.customer_id if order_snapshot else "customer"))),
        order_id=order_id if isinstance(order_id, str) else None,
        subscription_id=subscription_id if isinstance(subscription_id, str) else None,
        payment=payment_snapshot,
        order=order_snapshot,
        subscription=subscription_snapshot,
        payload=payload,
    )


def failure_category(event: NormalizedEvent) -> FailureCategory:
    if event.payment is None:
        return FailureCategory.CUSTOMER_ABANDONED
    try:
        return FailureCategory(event.payment.error_code or "")
    except ValueError:
        return map_error(event.payment.error_code)


__all__ = ["failure_category", "normalize"]
