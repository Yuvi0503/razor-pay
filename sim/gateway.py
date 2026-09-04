from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from backend.domain.contracts import OrderSnapshot, PaymentSnapshot, SubscriptionSnapshot
from backend.domain.enums import ActionType, OrderStatus, PaymentAttemptStatus

from .outcome_model import succeeds
from .scenarios import Scenario


@dataclass(slots=True)
class SimulatedGateway:
    seed: int
    scenarios: dict[str, Scenario] = field(default_factory=dict)
    payments: dict[str, PaymentSnapshot] = field(default_factory=dict)
    orders: dict[str, OrderSnapshot] = field(default_factory=dict)
    subscriptions: dict[str, SubscriptionSnapshot] = field(default_factory=dict)
    links: dict[str, dict[str, object]] = field(default_factory=dict)
    idempotent_results: dict[str, object] = field(default_factory=dict)

    def register(self, scenario: Scenario, now: datetime | None = None) -> None:
        """Create a failed provider state for a scenario."""
        now = now or datetime.now(UTC)
        self.scenarios[scenario.key] = scenario
        order_id = f"order_{scenario.key}"
        payment_id = f"payment_{scenario.key}_initial"
        order = OrderSnapshot(
            order_id=order_id,
            amount_paise=scenario.amount_paise,
            currency="INR",
            status=OrderStatus.ATTEMPTED,
            customer_id=f"customer_{scenario.key}",
            created_at=now - timedelta(hours=2),
        )
        self.orders[order_id] = order
        self.payments[payment_id] = PaymentSnapshot(
            payment_id=payment_id,
            amount_paise=scenario.amount_paise,
            status=PaymentAttemptStatus.FAILED,
            method="upi",
            issuer_or_bank="sim-bank",
            order_id=order_id,
            subscription_id=(f"sub_{scenario.key}" if scenario.case_class.value == "A_MANDATE" else None),
            error_code=scenario.failure_category.value,
            error_reason=scenario.failure_category.value,
            captured_at=None,
        )
        if scenario.case_class.value == "A_MANDATE":
            self.subscriptions[f"sub_{scenario.key}"] = SubscriptionSnapshot(
                subscription_id=f"sub_{scenario.key}",
                customer_id=order.customer_id,
                amount_paise=scenario.amount_paise,
                status="active",
                mandate_active=True,
                next_charge_at=now + timedelta(days=1),
            )

    def get_payment(self, payment_id: str) -> PaymentSnapshot:
        return self.payments[payment_id]

    def get_order(self, order_id: str) -> OrderSnapshot:
        return self.orders[order_id]

    def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        return self.subscriptions[subscription_id]

    def charge_mandate(
        self, subscription_id: str, amount_paise: int, idempotency_key: str
    ) -> PaymentSnapshot:
        previous = self.idempotent_results.get(idempotency_key)
        if isinstance(previous, PaymentSnapshot):
            return previous
        scenario = self.scenarios[subscription_id.removeprefix("sub_")]
        ok = succeeds(scenario, ActionType.RETRY_MANDATE_CHARGE, self.seed)
        payment = PaymentSnapshot(
            payment_id=f"payment_{scenario.key}_recovery",
            amount_paise=amount_paise,
            status=PaymentAttemptStatus.CAPTURED if ok else PaymentAttemptStatus.FAILED,
            method="upi",
            issuer_or_bank="sim-bank",
            subscription_id=subscription_id,
            error_code=None if ok else scenario.failure_category.value,
            error_reason=None if ok else scenario.failure_category.value,
            captured_at=datetime.now(UTC) if ok else None,
        )
        self.idempotent_results[idempotency_key] = payment
        self.payments[payment.payment_id] = payment
        return payment

    def create_payment_link(
        self, case_id: str, amount_paise: int, expires_at: datetime, idempotency_key: str
    ) -> dict[str, object]:
        previous = self.idempotent_results.get(idempotency_key)
        if isinstance(previous, dict):
            return previous
        key = case_id.removeprefix("case_")
        link = {
            "id": f"plink_{key}",
            "short_url": f"https://simulator.invalid/pay/{key}",
            "amount_paise": amount_paise,
            "expires_at": expires_at.isoformat(),
        }
        self.idempotent_results[idempotency_key] = link
        self.links[case_id] = link
        return link

    def list_stale_orders(self, before: datetime) -> list[OrderSnapshot]:
        return [
            order
            for order in self.orders.values()
            if order.created_at < before and order.status is not OrderStatus.PAID
        ]

    def execute(self, scenario: Scenario, action: ActionType | None) -> bool:
        self.register(scenario)
        ok = succeeds(scenario, action, self.seed)
        if ok:
            order = self.orders.get(f"order_{scenario.key}")
            if order:
                self.orders[order.order_id] = OrderSnapshot(
                    order_id=order.order_id,
                    amount_paise=order.amount_paise,
                    currency=order.currency,
                    status=OrderStatus.PAID,
                    customer_id=order.customer_id,
                    created_at=order.created_at,
                    last_payment_at=datetime.now(UTC),
                )
        return ok

    def execute_case(self, case: object, action: ActionType, idempotency_key: str) -> bool:
        """Execute a recovery action using only the public simulator boundary."""
        customer_id = getattr(case, "customer_id", "")
        key = customer_id.removeprefix("customer_")
        scenario = self.scenarios.get(key)
        if scenario is None:
            return False
        previous = self.idempotent_results.get(idempotency_key)
        if isinstance(previous, bool):
            return previous
        ok = succeeds(scenario, action, self.seed)
        self.idempotent_results[idempotency_key] = ok
        if ok:
            order = self.orders.get(f"order_{scenario.key}")
            if order:
                self.orders[order.order_id] = OrderSnapshot(
                    order_id=order.order_id,
                    amount_paise=order.amount_paise,
                    currency=order.currency,
                    status=OrderStatus.PAID,
                    customer_id=order.customer_id,
                    created_at=order.created_at,
                    last_payment_at=datetime.now(UTC),
                )
        return ok
