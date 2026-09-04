from datetime import UTC, datetime

import pytest

from backend.domain.contracts import (
    CaseSnapshot,
    OrderSnapshot,
    PaymentSnapshot,
    SubscriptionSnapshot,
)
from backend.domain.enums import CaseClass, FailureCategory, OrderStatus, PaymentAttemptStatus
from backend.domain.models import RecoveryCase

MONEY_FACTORIES = [
    (
        lambda amount: PaymentSnapshot("payment", amount, PaymentAttemptStatus.FAILED),
        "amount_paise",
    ),
    (
        lambda amount: OrderSnapshot(
            "order", amount, "INR", OrderStatus.ATTEMPTED, "customer", datetime.now(UTC)
        ),
        "amount_paise",
    ),
    (
        lambda amount: SubscriptionSnapshot("subscription", "customer", amount, "active", True),
        "amount_paise",
    ),
    (
        lambda amount: CaseSnapshot(
            "case", CaseClass.B_ONEOFF, amount, FailureCategory.UNKNOWN, "customer"
        ),
        "amount_at_risk_paise",
    ),
    (
        lambda amount: RecoveryCase(CaseClass.B_ONEOFF, amount, FailureCategory.UNKNOWN),
        "amount_at_risk_paise",
    ),
]


@pytest.mark.parametrize(
    ("factory", "field_name"), MONEY_FACTORIES,
)
def test_domain_money_boundaries_reject_float_and_negative_values(factory, field_name: str) -> None:
    with pytest.raises(TypeError, match="integer number of paise"):
        factory(999.5)
    with pytest.raises(ValueError, match="non-negative"):
        factory(-1)


@pytest.mark.parametrize(("factory", "field_name"), MONEY_FACTORIES)
def test_domain_money_boundaries_accept_integer_paise(factory, field_name: str) -> None:
    value = factory(99900)
    assert getattr(value, field_name) == 99900
