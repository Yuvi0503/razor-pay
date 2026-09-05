"""Normalize the small subset of provider payloads used by recovery."""

import hashlib
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
            parsed = datetime.fromisoformat(value)
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            return None
    return None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _paise(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _anonymous_customer_id(provider_event_id: str) -> str:
    """Return a stable internal placeholder that fits the 26-character ID column."""
    digest = hashlib.sha256(provider_event_id.encode()).hexdigest()
    return f"unknown_{digest[:18]}"


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
    event_type = _string(payload.get("event")) or "unknown"
    payment = _nested(payload, "payload", "payment", "entity")
    order = _nested(payload, "payload", "order", "entity")
    subscription = _nested(payload, "payload", "subscription", "entity")
    payment_id = _string(payment.get("id"))
    order_id = _string(payment.get("order_id")) or _string(order.get("id"))
    subscription_id = _string(payment.get("subscription_id")) or _string(subscription.get("id"))
    customer_id = (
        _string(payload.get("customer_id"))
        or _string(order.get("customer_id"))
        or _string(subscription.get("customer_id"))
        or _anonymous_customer_id(provider_event_id)
    )
    payment_status = PaymentAttemptStatus.FAILED if event_type.endswith("failed") else PaymentAttemptStatus.CAPTURED
    payment_snapshot = None
    payment_amount = _paise(payment.get("amount"))
    if payment_id and payment_amount is not None and (order_id or subscription_id):
        payment_snapshot = PaymentSnapshot(
            payment_id=payment_id,
            amount_paise=payment_amount,
            status=payment_status,
            method=_string(payment.get("method")),
            issuer_or_bank=_string(payment.get("bank")) or _string(payment.get("issuer")),
            order_id=order_id,
            subscription_id=subscription_id,
            error_code=_string(_nested(payment, "error").get("code")),
            error_reason=_string(_nested(payment, "error").get("reason")),
            captured_at=None if payment_status is PaymentAttemptStatus.FAILED else _time(payment.get("created_at")),
        )
    order_snapshot = None
    order_amount = _paise(order.get("amount"))
    if order_amount is None:
        order_amount = payment_amount
    if order_id and order_amount is not None:
        status = OrderStatus.PAID if event_type in {"order.paid", "payment.captured"} else OrderStatus.ATTEMPTED
        order_snapshot = OrderSnapshot(
            order_id=order_id,
            amount_paise=order_amount,
            currency=_string(order.get("currency")) or "INR",
            status=status,
            customer_id=customer_id,
            created_at=_time(order.get("created_at")) or received_at or datetime.now(UTC),
        )
    subscription_snapshot = None
    subscription_amount = _paise(subscription.get("amount"))
    if subscription_amount is None:
        subscription_amount = payment_amount
    if subscription_id and subscription_amount is not None:
        subscription_snapshot = SubscriptionSnapshot(
            subscription_id=subscription_id,
            customer_id=customer_id,
            amount_paise=subscription_amount,
            status=_string(subscription.get("status")) or "active",
            mandate_active=(_string(subscription.get("status")) or "active") not in {"cancelled", "halted"},
            next_charge_at=_time(subscription.get("charge_at")),
        )
    return NormalizedEvent(
        provider_event_id=provider_event_id,
        event_type=event_type,
        received_at=received_at or datetime.now(UTC),
        merchant_id=_string(payload.get("merchant_id")) or "merchant",
        customer_id=customer_id,
        order_id=order_id,
        subscription_id=subscription_id,
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
