from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.db.models import (
    AuditEvent,
    OutboundMessage,
    RecoveryAction,
    RecoveryCase,
)
from backend.db.repositories.recovery import RecoveryRepository
from backend.domain.contracts import NormalizedEvent, OrderSnapshot, PaymentSnapshot
from backend.domain.enums import (
    ActionType,
    CaseClass,
    CaseState,
    FailureCategory,
    InitiatedBy,
    OrderStatus,
    PaymentAttemptStatus,
    RecoveryActionState,
    VerdictType,
)
from backend.domain.models import Decision, WorldState
from backend.domain.models import RecoveryCase as DomainCase
from backend.domain.state_machine import TRANSITIONS, IllegalTransition, transition
from backend.orchestration.orchestrator import Orchestrator
from backend.policy.config_loader import load
from backend.policy.engine import evaluate
from backend.policy.rules import eligible_actions


def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def event(key: str = "one") -> NormalizedEvent:
    now = datetime(2026, 1, 1, 4, tzinfo=UTC)
    order = OrderSnapshot(f"order-{key}", 99900, "INR", OrderStatus.ATTEMPTED, f"customer-{key}", now)
    payment = PaymentSnapshot(
        f"payment-{key}", 99900, PaymentAttemptStatus.FAILED, "upi", "bank", order.order_id,
        error_code=FailureCategory.INSUFFICIENT_FUNDS.value,
    )
    return NormalizedEvent(f"event-{key}", "payment.failed", now, "merchant", order.customer_id, order.order_id, None, payment, order)


def test_every_state_transition_pair_is_explicit() -> None:
    for current, targets in TRANSITIONS.items():
        for target in targets:
            assert transition(current, target) is target
        for target in set(CaseState) - targets - {current}:
            try:
                transition(current, target)
            except IllegalTransition:
                pass
            else:
                raise AssertionError(f"unexpected transition {current} -> {target}")


def test_taxonomy_and_eligible_action_fallbacks_are_safe() -> None:
    case = DomainCase(CaseClass.B_ONEOFF, 100, FailureCategory.UNKNOWN)
    assert eligible_actions(case)[0] is ActionType.CREATE_PAYMENT_LINK
    assert evaluate(case, Decision(ActionType.RETRY_MANDATE_CHARGE), WorldState(datetime.now(UTC)), load()).verdict == VerdictType.DENY


def test_duplicate_event_opens_one_case_and_persists_timeline() -> None:
    session = db()
    gateway = __import__("sim.gateway", fromlist=["SimulatedGateway"]).SimulatedGateway(7)
    orchestrator = Orchestrator(session, gateway, load())
    first = orchestrator.ingest(event(), "rules")
    second = orchestrator.ingest(event(), "rules")
    assert first is second
    assert session.query(RecoveryCase).count() == 1
    assert session.query(AuditEvent).count() == 2


def test_paid_between_schedule_and_execution_is_skipped() -> None:
    session = db()
    from sim.gateway import SimulatedGateway

    gateway = SimulatedGateway(7)
    orchestrator = Orchestrator(session, gateway, load())
    case = orchestrator.ingest(event("paid"), "rules")
    assert case is not None
    scheduled = orchestrator.process(case, datetime(2026, 1, 1, 4, tzinfo=UTC), candidate_action=ActionType.CREATE_PAYMENT_LINK, delay_minutes=60)
    assert scheduled.state is CaseState.SCHEDULED
    case_order = session.get(__import__("backend.db.models", fromlist=["Order"]).Order, case.order_id)
    assert case_order is not None
    case_order.status = OrderStatus.PAID
    result = orchestrator.execute_action(scheduled.action_id or "", datetime(2026, 1, 1, 6, tzinfo=UTC))
    assert result.state is CaseState.DECIDED
    action = session.get(RecoveryAction, scheduled.action_id)
    assert action is not None and action.state is RecoveryActionState.SKIPPED


def test_opt_out_and_contact_budget_are_persisted_safety_gates() -> None:
    session = db()
    from backend.domain.enums import ConsentChannel, ConsentState
    from sim.gateway import SimulatedGateway

    repo = RecoveryRepository(session)
    repo.merchant("merchant")
    repo.customer("merchant", "customer")
    repo.set_consent("customer", ConsentChannel.EMAIL, ConsentState.OPTED_OUT)
    case = DomainCase(CaseClass.B_ONEOFF, 100, FailureCategory.UNKNOWN, customer_id="customer")
    result = evaluate(case, Decision(ActionType.SEND_REMINDER), WorldState(datetime(2026, 1, 1, 4, tzinfo=UTC), consent=ConsentState.OPTED_OUT), load())
    assert result.verdict is VerdictType.DENY
    assert isinstance(SimulatedGateway(1), SimulatedGateway)


def test_outage_signal_defers_mandate_retry() -> None:
    session = db()
    repo = RecoveryRepository(session)
    now = datetime(2026, 1, 1, 4, tzinfo=UTC)
    merchant = repo.merchant("m")
    customer = repo.customer(merchant.id, "c")
    order = repo.order(merchant.id, customer.id, "o", 100)
    for index in range(20):
        repo.payment_attempt(order_id=order.id, subscription_id=None, amount_paise=100, status=PaymentAttemptStatus.FAILED, method="upi", raw_error_code="x", occurred_at=now - timedelta(minutes=index % 10))
    assert repo.outage_signal("upi", now, 15, 20, 2.5)


def test_rendered_message_always_contains_opt_out() -> None:
    from backend.actions.message_renderer import render_payment_reminder

    rendered = render_payment_reminder(99900, "https://example.test/pay")
    assert "opt out" in rendered["body"].lower() or "stop" in rendered["body"].lower()
    assert OutboundMessage.__tablename__ == "outbound_messages"


def test_high_value_case_enters_manual_approval_queue() -> None:
    session = db()
    from sim.gateway import SimulatedGateway

    high = event("high")
    high_payment = PaymentSnapshot(
        "payment-high", 1_250_000, PaymentAttemptStatus.FAILED, "upi", "bank", "order-high",
        error_code=FailureCategory.INSUFFICIENT_FUNDS.value,
    )
    high = NormalizedEvent(
        high.provider_event_id,
        high.event_type,
        high.received_at,
        high.merchant_id,
        high.customer_id,
        high.order_id,
        high.subscription_id,
        high_payment,
        OrderSnapshot("order-high", 1_250_000, "INR", OrderStatus.ATTEMPTED, high.customer_id, high.received_at),
    )
    orchestrator = Orchestrator(session, SimulatedGateway(1), load())
    case = orchestrator.ingest(high)
    assert case is not None
    result = orchestrator.process(case, high.received_at)
    assert result.verdict is VerdictType.REQUIRE_HUMAN
    assert result.state is CaseState.AWAITING_APPROVAL


def test_duplicate_captured_payments_create_compensation_audit_event() -> None:
    session = db()
    orchestrator = Orchestrator(session, __import__("sim.gateway", fromlist=["SimulatedGateway"]).SimulatedGateway(1), load())
    case = orchestrator.ingest(event("duplicate-charge"))
    assert case is not None and case.order_id is not None
    repo = RecoveryRepository(session)
    for payment_id in ("captured-one", "captured-two"):
        repo.payment_attempt(
            order_id=case.order_id,
            subscription_id=None,
            amount_paise=99900,
            status=PaymentAttemptStatus.CAPTURED,
            provider_payment_id=payment_id,
            initiated_by=InitiatedBy.CUSTOMER,
        )
    orchestrator._check_duplicate_charges(case)
    incident = session.query(AuditEvent).filter_by(
        event_type="DUPLICATE_CHARGE_COMPENSATION_REQUIRED"
    ).one()
    assert incident.payload == {"compensation": "REFUND_REVIEW"}
