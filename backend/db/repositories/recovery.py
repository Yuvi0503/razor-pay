"""Small transaction-aware repositories used by the recovery pipeline."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.enums import (
    ActionType,
    AuditActor,
    ClassifiedBy,
    ConsentChannel,
    ConsentState,
    DecisionSource,
    FailureCategory,
    GeneratedBy,
    InitiatedBy,
    MessageChannel,
    PaymentAttemptStatus,
    Recoverability,
    RecoveryActionState,
    VerdictType,
)

from ..models import (
    AuditEvent,
    Customer,
    CustomerConsent,
    Merchant,
    Order,
    OutboundMessage,
    PaymentAttempt,
    PolicyEvaluation,
    RecoveryAction,
    RecoveryCase,
    RecoveryDecision,
    Subscription,
)


class RecoveryRepository:
    """Repository with no implicit commits, so callers retain transaction control."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def merchant(self, merchant_id: str, name: str = "Demo merchant") -> Merchant:
        item = self.session.get(Merchant, merchant_id)
        if item is None:
            item = Merchant(id=merchant_id, name=name)
            self.session.add(item)
            self.session.flush()
        return item

    def customer(self, merchant_id: str, customer_id: str) -> Customer:
        item = self.session.get(Customer, customer_id)
        if item is None:
            item = Customer(id=customer_id, merchant_id=merchant_id, external_ref=customer_id)
            self.session.add(item)
            self.session.flush()
        return item

    def consent(self, customer_id: str, channel: ConsentChannel) -> ConsentState:
        item = self.session.scalar(
            select(CustomerConsent).where(
                CustomerConsent.customer_id == customer_id,
                CustomerConsent.channel == channel,
            )
        )
        return item.state if item else ConsentState.UNKNOWN

    def set_consent(
        self, customer_id: str, channel: ConsentChannel, state: ConsentState, source: str = "system"
    ) -> CustomerConsent:
        item = self.session.scalar(
            select(CustomerConsent).where(
                CustomerConsent.customer_id == customer_id,
                CustomerConsent.channel == channel,
            )
        )
        if item is None:
            item = CustomerConsent(
                customer_id=customer_id,
                channel=channel,
                state=state,
                captured_at=datetime.now(UTC),
                source=source,
            )
            self.session.add(item)
        else:
            item.state = state
            item.captured_at = datetime.now(UTC)
            item.source = source
        self.session.flush()
        return item

    def order(
        self,
        merchant_id: str,
        customer_id: str,
        provider_order_id: str,
        amount_paise: int,
        currency: str = "INR",
        status: Any = "CREATED",
    ) -> Order:
        item = self.session.scalar(select(Order).where(Order.provider_order_id == provider_order_id))
        if item is None:
            item = Order(
                merchant_id=merchant_id,
                customer_id=customer_id,
                provider_order_id=provider_order_id,
                amount_paise=amount_paise,
                currency=currency,
                status=status,
            )
            self.session.add(item)
            self.session.flush()
        else:
            item.status = status
        return item

    def subscription(
        self,
        customer_id: str,
        provider_sub_id: str,
        amount_paise: int,
        status: str = "active",
        mandate_active: bool = True,
    ) -> Subscription:
        item = self.session.scalar(
            select(Subscription).where(Subscription.provider_sub_id == provider_sub_id)
        )
        if item is None:
            item = Subscription(
                customer_id=customer_id,
                provider_sub_id=provider_sub_id,
                amount_paise=amount_paise,
                status=status,
                mandate_active=mandate_active,
            )
            self.session.add(item)
            self.session.flush()
        return item

    def payment_attempt(
        self,
        *,
        order_id: str | None,
        subscription_id: str | None,
        amount_paise: int,
        status: PaymentAttemptStatus,
        provider_payment_id: str | None = None,
        method: str | None = None,
        issuer_or_bank: str | None = None,
        raw_error_code: str | None = None,
        raw_error_reason: str | None = None,
        failure_category: FailureCategory | None = None,
        classified_by: ClassifiedBy | None = None,
        initiated_by: InitiatedBy = InitiatedBy.CUSTOMER,
        occurred_at: datetime | None = None,
    ) -> PaymentAttempt:
        if provider_payment_id:
            existing = self.session.scalar(
                select(PaymentAttempt).where(
                    PaymentAttempt.provider_payment_id == provider_payment_id
                )
            )
            if existing:
                return existing
        parent_column = PaymentAttempt.order_id if order_id else PaymentAttempt.subscription_id
        parent_id = order_id or subscription_id
        number = self.session.scalar(
            select(func.count(PaymentAttempt.id)).where(parent_column == parent_id)
        ) or 0
        item = PaymentAttempt(
            order_id=order_id,
            subscription_id=subscription_id,
            attempt_number=int(number) + 1,
            provider_payment_id=provider_payment_id,
            method=method,
            issuer_or_bank=issuer_or_bank,
            amount_paise=amount_paise,
            status=status,
            raw_error_code=raw_error_code,
            raw_error_reason=raw_error_reason,
            failure_category=failure_category,
            classified_by=classified_by,
            initiated_by=initiated_by,
            occurred_at=occurred_at or datetime.now(UTC),
        )
        self.session.add(item)
        self.session.flush()
        return item

    def open_case(
        self,
        *,
        merchant_id: str,
        customer_id: str,
        order_id: str | None,
        subscription_id: str | None,
        case_class: Any,
        amount_paise: int,
        failure_category: FailureCategory,
        recoverability: Recoverability,
        experiment_arm: str | None = None,
    ) -> RecoveryCase:
        statement = select(RecoveryCase).where(RecoveryCase.resolved_at.is_(None))
        if order_id:
            statement = statement.where(RecoveryCase.order_id == order_id)
        elif subscription_id:
            statement = statement.where(RecoveryCase.subscription_id == subscription_id)
        existing = self.session.scalar(statement)
        if existing:
            return existing
        item = RecoveryCase(
            merchant_id=merchant_id,
            customer_id=customer_id,
            order_id=order_id,
            subscription_id=subscription_id,
            case_class=case_class,
            amount_at_risk_paise=amount_paise,
            failure_category=failure_category,
            recoverability=recoverability,
            experiment_arm=experiment_arm,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def decision(
        self,
        case_id: str,
        action: ActionType,
        delay_minutes: int,
        source: DecisionSource,
        reason_codes: list[str],
        input_snapshot: dict[str, Any],
        rule_id: str | None = None,
        llm_model: str | None = None,
        llm_prompt_version: str | None = None,
        llm_cache_key: str | None = None,
        llm_fallback_reason: str | None = None,
        llm_confidence: float | None = None,
        llm_raw_response: dict[str, Any] | None = None,
        llm_latency_ms: int | None = None,
    ) -> RecoveryDecision:
        item = RecoveryDecision(
            case_id=case_id,
            proposed_action=action,
            proposed_delay_minutes=delay_minutes,
            source=source,
            rule_id=rule_id,
            reason_codes=reason_codes,
            input_snapshot=input_snapshot,
            llm_model=llm_model,
            llm_prompt_version=llm_prompt_version,
            llm_cache_key=llm_cache_key,
            llm_fallback_reason=llm_fallback_reason,
            llm_confidence=llm_confidence,
            llm_raw_response=llm_raw_response,
            llm_latency_ms=llm_latency_ms,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def policy_evaluation(
        self,
        decision_id: str,
        case_id: str,
        verdict: VerdictType,
        final_action: ActionType | None,
        rules_fired: list[dict[str, Any]],
        policy_config_hash: str,
    ) -> PolicyEvaluation:
        item = PolicyEvaluation(
            decision_id=decision_id,
            case_id=case_id,
            verdict=verdict,
            final_action=final_action,
            rules_fired=rules_fired,
            policy_config_hash=policy_config_hash,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def action(
        self,
        *,
        case_id: str,
        policy_evaluation_id: str,
        action_type: ActionType,
        idempotency_key: str,
        scheduled_for: datetime,
    ) -> RecoveryAction:
        existing = self.session.scalar(
            select(RecoveryAction).where(RecoveryAction.idempotency_key == idempotency_key)
        )
        if existing:
            return existing
        item = RecoveryAction(
            case_id=case_id,
            policy_evaluation_id=policy_evaluation_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            scheduled_for=scheduled_for,
            state=RecoveryActionState.SCHEDULED,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def contacts_last_7d(self, customer_id: str, now: datetime) -> int:
        cutoff = now - timedelta(days=7)
        return int(
            self.session.scalar(
                select(func.count(OutboundMessage.id)).where(
                    OutboundMessage.case_id.in_(
                        select(RecoveryCase.id).where(RecoveryCase.customer_id == customer_id)
                    ),
                    OutboundMessage.created_at >= cutoff,
                )
            )
            or 0
        )

    def attempts_for_rail(
        self, method: str | None, now: datetime, window: timedelta, issuer_or_bank: str | None = None
    ) -> int:
        statement = select(func.count(PaymentAttempt.id)).where(
            PaymentAttempt.occurred_at >= now - window,
            PaymentAttempt.method == method,
        )
        if issuer_or_bank is not None:
            statement = statement.where(PaymentAttempt.issuer_or_bank == issuer_or_bank)
        return int(self.session.scalar(statement) or 0)

    def failed_attempts_for_rail(
        self, method: str | None, issuer_or_bank: str | None, start: datetime, end: datetime
    ) -> int:
        statement = select(func.count(PaymentAttempt.id)).where(
            PaymentAttempt.occurred_at >= start,
            PaymentAttempt.occurred_at < end,
            PaymentAttempt.method == method,
            PaymentAttempt.issuer_or_bank == issuer_or_bank,
            PaymentAttempt.status == PaymentAttemptStatus.FAILED,
        )
        return int(self.session.scalar(statement) or 0)

    def outage_signal(
        self,
        method: str | None,
        now: datetime,
        window_minutes: int,
        minimum_attempts: int,
        failure_multiplier: float,
        issuer_or_bank: str | None = None,
    ) -> bool:
        recent_start = now - timedelta(minutes=window_minutes)
        recent_total = self.attempts_for_rail(method, now, timedelta(minutes=window_minutes), issuer_or_bank)
        if recent_total < minimum_attempts:
            return False
        recent_failed = self.failed_attempts_for_rail(method, issuer_or_bank, recent_start, now)
        baseline_start = now - timedelta(hours=24)
        baseline_end = recent_start
        baseline_total = self.attempts_for_rail(method, baseline_end, timedelta(hours=24 - window_minutes / 60), issuer_or_bank)
        baseline_failed = self.failed_attempts_for_rail(method, issuer_or_bank, baseline_start, baseline_end)
        if baseline_total == 0:
            return recent_failed == recent_total
        return (recent_failed / recent_total) >= (baseline_failed / baseline_total) * failure_multiplier

    def audit(
        self,
        event_type: str,
        actor: AuditActor,
        case_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        item = AuditEvent(case_id=case_id, event_type=event_type, actor=actor, payload=payload)
        self.session.add(item)
        self.session.flush()
        return item

    def message(
        self,
        case_id: str,
        action_id: str,
        channel: MessageChannel,
        template_id: str,
        body: str,
        subject: str | None = None,
    ) -> OutboundMessage:
        item = OutboundMessage(
            case_id=case_id,
            action_id=action_id,
            channel=channel,
            template_id=template_id,
            rendered_subject=subject,
            rendered_body=body,
            generated_by=GeneratedBy.TEMPLATE,
        )
        self.session.add(item)
        self.session.flush()
        return item


__all__ = ["RecoveryRepository"]
