"""Typed boundaries between provider ingestion, policy, and execution.

These contracts deliberately contain provider-neutral values.  The Razorpay
adapter and the simulator are responsible for translating their own payloads
into these small snapshots.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .enums import CaseClass, FailureCategory, OrderStatus, PaymentAttemptStatus
from .money import require_paise


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PaymentSnapshot:
    payment_id: str
    amount_paise: int
    status: PaymentAttemptStatus
    method: str | None = None
    issuer_or_bank: str | None = None
    order_id: str | None = None
    subscription_id: str | None = None
    error_code: str | None = None
    error_reason: str | None = None
    captured_at: datetime | None = None

    def __post_init__(self) -> None:
        require_paise(self.amount_paise)


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    order_id: str
    amount_paise: int
    currency: str
    status: OrderStatus
    customer_id: str
    created_at: datetime
    last_payment_at: datetime | None = None

    def __post_init__(self) -> None:
        require_paise(self.amount_paise)


@dataclass(frozen=True, slots=True)
class SubscriptionSnapshot:
    subscription_id: str
    customer_id: str
    amount_paise: int
    status: str
    mandate_active: bool
    next_charge_at: datetime | None = None

    def __post_init__(self) -> None:
        require_paise(self.amount_paise)


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    provider_event_id: str
    event_type: str
    received_at: datetime = field(default_factory=utcnow)
    merchant_id: str = "merchant"
    customer_id: str = "customer"
    order_id: str | None = None
    subscription_id: str | None = None
    payment: PaymentSnapshot | None = None
    order: OrderSnapshot | None = None
    subscription: SubscriptionSnapshot | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_failed_payment(self) -> bool:
        return self.payment is not None and self.payment.status is PaymentAttemptStatus.FAILED


@dataclass(frozen=True, slots=True)
class CaseSnapshot:
    case_id: str
    case_class: CaseClass
    amount_at_risk_paise: int
    failure_category: FailureCategory
    customer_id: str
    order_id: str | None = None
    subscription_id: str | None = None

    def __post_init__(self) -> None:
        require_paise(self.amount_at_risk_paise, "amount_at_risk_paise")


__all__ = [
    "CaseSnapshot",
    "NormalizedEvent",
    "OrderSnapshot",
    "PaymentSnapshot",
    "SubscriptionSnapshot",
]
