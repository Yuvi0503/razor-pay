"""Synchronous recovery orchestration used by the API worker and simulator."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.actions.message_renderer import render_payment_reminder
from backend.actions.registry import REGISTRY
from backend.db.models import (
    HumanApproval,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryDecision,
)
from backend.db.repositories.recovery import RecoveryRepository
from backend.domain.contracts import NormalizedEvent, OrderSnapshot
from backend.domain.enums import (
    ActionType,
    ApprovalDecision,
    AuditActor,
    CaseClass,
    CaseState,
    ClassifiedBy,
    ConsentChannel,
    DecisionSource,
    FailureCategory,
    InitiatedBy,
    MessageChannel,
    PaymentAttemptStatus,
    Recoverability,
    RecoveryActionState,
    RecoveryResolution,
    VerdictType,
)
from backend.domain.failure_taxonomy import map_error
from backend.domain.models import Decision, WorldState
from backend.domain.models import RecoveryCase as DomainCase
from backend.domain.recoverability import derive
from backend.domain.state_machine import transition
from backend.gateway.base import GatewayAdapter
from backend.llm.contracts import LLMDecision
from backend.policy.config_loader import PolicyConfig
from backend.policy.engine import evaluate
from backend.policy.rules import first_eligible


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
from backend.scheduler import schedule_action


@dataclass(frozen=True, slots=True)
class PipelineResult:
    case_id: str
    action_id: str | None
    state: CaseState
    verdict: VerdictType | None
    recovered: bool
    policy_violation: bool = False


class Orchestrator:
    def __init__(
        self,
        session: Session,
        gateway: GatewayAdapter,
        policy: PolicyConfig,
        scheduler: BackgroundScheduler | None = None,
    ) -> None:
        self.session = session
        self.gateway = gateway
        self.policy = policy
        self.scheduler = scheduler
        self.repo = RecoveryRepository(session)

    def ingest(
        self,
        event: NormalizedEvent,
        experiment_arm: str | None = None,
        *,
        failure_category_override: FailureCategory | None = None,
        classified_by: ClassifiedBy = ClassifiedBy.RULE,
    ) -> RecoveryCase | None:
        """Persist normalized provider data and open a case when it is actionable."""
        self.repo.merchant(event.merchant_id)
        self.repo.customer(event.merchant_id, event.customer_id)
        order = None
        if event.order:
            order = self.repo.order(
                event.merchant_id,
                event.customer_id,
                event.order.order_id,
                event.order.amount_paise,
                event.order.currency,
                event.order.status,
            )
        subscription = None
        if event.subscription:
            subscription = self.repo.subscription(
                event.customer_id,
                event.subscription.subscription_id,
                event.subscription.amount_paise,
                event.subscription.status,
                event.subscription.mandate_active,
            )
        if event.payment is None:
            return None
        category = failure_category_override or self._category(event)
        attempt = self.repo.payment_attempt(
            order_id=order.id if order else None,
            subscription_id=subscription.id if subscription else None,
            amount_paise=event.payment.amount_paise,
            status=event.payment.status,
            provider_payment_id=event.payment.payment_id,
            method=event.payment.method,
            issuer_or_bank=event.payment.issuer_or_bank,
            raw_error_code=event.payment.error_code,
            raw_error_reason=event.payment.error_reason,
            failure_category=category,
            classified_by=classified_by,
            occurred_at=event.received_at,
        )
        if event.payment.status is not PaymentAttemptStatus.FAILED:
            self._mark_paid(order.id if order else None)
            open_case = self.session.scalar(
                select(RecoveryCase).where(
                    RecoveryCase.order_id == (order.id if order else None),
                    RecoveryCase.resolved_at.is_(None),
                )
            )
            if open_case and open_case.state is CaseState.SCHEDULED:
                self._move(open_case, CaseState.DECIDED, "PAYMENT_CAPTURED_BEFORE_ACTION", None)
            if open_case and open_case.state is CaseState.DECIDED:
                transition(open_case.state, CaseState.RECOVERED)
                open_case.state = CaseState.RECOVERED
                open_case.resolution = RecoveryResolution.RECOVERED
                open_case.recovered_amount_paise = event.payment.amount_paise
                open_case.recovered_attempt_id = attempt.id
                open_case.resolved_at = event.received_at
                self.repo.audit("RECOVERY_VERIFIED", AuditActor.GATEWAY, open_case.id, {"payment_id": attempt.provider_payment_id})
            self.repo.audit(
                "PAYMENT_CAPTURED",
                AuditActor.GATEWAY,
                open_case.id if open_case else None,
                {"payment_id": attempt.provider_payment_id},
            )
            return None
        case_class = CaseClass.A_MANDATE if subscription else CaseClass.B_ONEOFF
        case = self.repo.open_case(
            merchant_id=event.merchant_id,
            customer_id=event.customer_id,
            order_id=order.id if order else None,
            subscription_id=subscription.id if subscription else None,
            case_class=case_class,
            amount_paise=event.payment.amount_paise,
            failure_category=category,
            recoverability=derive(case_class, category),
            experiment_arm=experiment_arm,
        )
        self.repo.audit(
            "CASE_OPENED" if case.state is CaseState.OPEN else "CASE_DEDUPLICATED",
            AuditActor.SYSTEM,
            case.id,
            {"provider_event_id": event.provider_event_id, "payment_attempt_id": attempt.id},
        )
        self.session.flush()
        return case

    def ingest_stale_order(
        self, merchant_id: str, order: OrderSnapshot, provider_event_id: str, experiment_arm: str | None = None
    ) -> RecoveryCase:
        """Open a class-C case from a sweeper result without inventing a payment failure."""
        self.repo.merchant(merchant_id)
        self.repo.customer(merchant_id, order.customer_id)
        stored_order = self.repo.order(
            merchant_id,
            order.customer_id,
            order.order_id,
            order.amount_paise,
            order.currency,
            order.status,
        )
        case = self.repo.open_case(
            merchant_id=merchant_id,
            customer_id=order.customer_id,
            order_id=stored_order.id,
            subscription_id=None,
            case_class=CaseClass.C_ABANDONED,
            amount_paise=order.amount_paise,
            failure_category=FailureCategory.CUSTOMER_ABANDONED,
            recoverability=Recoverability.ASSISTED,
            experiment_arm=experiment_arm,
        )
        self.repo.audit("STALE_ORDER_OPENED", AuditActor.SYSTEM, case.id, {"provider_event_id": provider_event_id})
        self.session.flush()
        return case

    def process(
        self,
        case: RecoveryCase,
        now: datetime | None = None,
        auto_approve: bool = False,
        candidate_action: ActionType | None = None,
        delay_minutes: int = 0,
        execute_immediately: bool = False,
        continue_on_failure: bool = False,
        decision_source: DecisionSource = DecisionSource.RULE,
        llm_decision: LLMDecision | None = None,
        llm_model: str | None = None,
        llm_prompt_version: str | None = None,
        llm_cache_key: str | None = None,
        llm_fallback_reason: str | None = None,
        llm_raw_response: dict[str, Any] | None = None,
        llm_latency_ms: int | None = None,
        decision_input_snapshot: dict[str, Any] | None = None,
        decision_reason_codes: list[str] | None = None,
    ) -> PipelineResult:
        now = now or datetime.now(UTC)
        if case.state is CaseState.OPEN:
            self._move(case, CaseState.CLASSIFIED, "CASE_CLASSIFIED", {"category": case.failure_category.value})
        action, reasons = first_eligible(
            DomainCase(
                case_class=case.case_class,
                amount_at_risk_paise=case.amount_at_risk_paise,
                failure_category=case.failure_category,
                customer_id=case.customer_id,
                order_id=case.order_id,
                subscription_id=case.subscription_id,
            )
        )
        if candidate_action is not None:
            action = candidate_action
            reasons = [f"CANDIDATE_{candidate_action.value}"]
        if decision_reason_codes:
            reasons = [*reasons, *decision_reason_codes]
        delay = delay_minutes
        if case.state is CaseState.CLASSIFIED:
            self._move(case, CaseState.DECIDED, "DECISION_PROPOSED", {"action": action.value})
        decision = self.repo.decision(
            case.id,
            action,
            delay,
            decision_source,
            reasons,
            {
                "case_class": case.case_class.value,
                "failure_category": case.failure_category.value,
                **(decision_input_snapshot or {}),
            },
            llm_model=llm_model if llm_decision or llm_fallback_reason else None,
            llm_prompt_version=llm_prompt_version,
            llm_cache_key=llm_cache_key,
            llm_fallback_reason=llm_fallback_reason,
            llm_confidence=llm_decision.confidence if llm_decision else None,
            llm_raw_response=llm_raw_response,
            llm_latency_ms=llm_latency_ms,
        )
        domain_case = DomainCase(
            case_class=case.case_class,
            amount_at_risk_paise=case.amount_at_risk_paise,
            failure_category=case.failure_category,
            customer_id=case.customer_id,
            order_id=case.order_id,
            subscription_id=case.subscription_id,
            state=case.state,
            contacts_used=case.contacts_used,
            charge_attempts_used=case.charge_attempts_used,
            opened_at=_aware(case.opened_at),
            last_action_at=None,
            id=case.id,
        )
        consent = self.repo.consent(case.customer_id, ConsentChannel.EMAIL)
        world = WorldState(
            now=now,
            consent=consent,
            customer_contacts_7d=self.repo.contacts_last_7d(case.customer_id, now),
            paid=self._is_paid(case),
            chargeable=case.recoverability.value != "NOT_RECOVERABLE",
            rail_degraded=self._rail_degraded(case, now),
        )
        verdict = evaluate(domain_case, Decision(action, delay, reason_codes=tuple(reasons)), world, self.policy)
        evaluation = self.repo.policy_evaluation(
            decision.id,
            case.id,
            VerdictType(verdict.verdict),
            verdict.final_action,
            [{"rule_id": r.rule_id, "passed": r.passed, "detail": r.detail} for r in verdict.rules_fired],
            self.policy.config_hash,
        )
        self.repo.audit(
            "POLICY_EVALUATED",
            AuditActor.RULE,
            case.id,
            {"verdict": verdict.verdict, "rules": [r.rule_id for r in verdict.rules_fired]},
        )
        if not self.policy.values["regulatory_retry_cap"]["enabled"]:
            self.repo.audit("NOT_VERIFIED_A2_RETRY_CAP_DISABLED", AuditActor.SYSTEM, case.id)
        if not self.policy.values["pre_debit_notice"]["enabled"]:
            self.repo.audit("NOT_VERIFIED_A3_PRE_DEBIT_DISABLED", AuditActor.SYSTEM, case.id)
        if verdict.verdict is VerdictType.REQUIRE_HUMAN:
            approval = HumanApproval(case_id=case.id, decision_id=decision.id)
            self.session.add(approval)
            self._move(case, CaseState.AWAITING_APPROVAL, "APPROVAL_REQUIRED", None)
            self.session.flush()
            if not auto_approve:
                return PipelineResult(case.id, None, case.state, VerdictType.REQUIRE_HUMAN, False)
            approval.decision = ApprovalDecision.APPROVED
            approval.decided_at = now
            self.repo.audit("APPROVAL_GRANTED", AuditActor.HUMAN, case.id, {"mode": "simulated"})
            world = WorldState(
                now=now,
                consent=consent,
                customer_contacts_7d=self.repo.contacts_last_7d(case.customer_id, now),
                paid=self._is_paid(case),
                chargeable=case.recoverability.value != "NOT_RECOVERABLE",
                rail_degraded=self._rail_degraded(case, now),
                approval_granted=True,
            )
            verdict = evaluate(domain_case, Decision(action, delay, reason_codes=tuple(reasons)), world, self.policy)
            evaluation = self.repo.policy_evaluation(
                decision.id,
                case.id,
                VerdictType(verdict.verdict),
                verdict.final_action,
                [{"rule_id": r.rule_id, "passed": r.passed, "detail": r.detail} for r in verdict.rules_fired],
                self.policy.config_hash,
            )
            self._move(case, CaseState.DECIDED, "APPROVAL_REVALIDATED", None)
        if verdict.verdict is not VerdictType.ALLOW or verdict.final_action is None:
            self._resolve(case, RecoveryResolution.STOPPED if verdict.verdict is VerdictType.DENY else RecoveryResolution.EXHAUSTED)
            self.session.flush()
            return PipelineResult(case.id, None, case.state, VerdictType(verdict.verdict), False)
        action = verdict.final_action
        scheduled_for = now + timedelta(minutes=delay)
        key = hashlib.sha256(
            f"{case.id}:{action.value}:{case.charge_attempts_used}:{scheduled_for.isoformat()}".encode()
        ).hexdigest()
        action_row = self.repo.action(
            case_id=case.id,
            policy_evaluation_id=evaluation.id,
            action_type=action,
            idempotency_key=key,
            scheduled_for=scheduled_for,
        )
        self._move(case, CaseState.SCHEDULED, "ACTION_SCHEDULED", {"action_id": action_row.id})
        if self.scheduler is not None:
            schedule_action(self.scheduler, action_row.id, scheduled_for)
        self.session.flush()
        if not execute_immediately:
            return PipelineResult(case.id, action_row.id, case.state, VerdictType.ALLOW, False)
        return self.execute_action(
            action_row.id,
            now=scheduled_for,
            continue_on_failure=continue_on_failure,
        )

    def execute_action(
        self,
        action_id: str,
        now: datetime | None = None,
        continue_on_failure: bool = False,
    ) -> PipelineResult:
        now = now or datetime.now(UTC)
        action = self.session.get(RecoveryAction, action_id)
        if action is None:
            raise LookupError(action_id)
        case = self.session.get(RecoveryCase, action.case_id)
        if case is None:
            raise LookupError(action.case_id)
        if case.state is not CaseState.SCHEDULED:
            action.state = RecoveryActionState.SKIPPED
            action.skip_reason = "case is not scheduled"
            self.session.flush()
            return PipelineResult(case.id, action.id, case.state, None, False)
        if now < _aware(action.scheduled_for):
            return PipelineResult(case.id, action.id, case.state, None, False)
        if now - _aware(case.opened_at) > timedelta(hours=int(self.policy.values["max_case_age_hours"])):
            action.state = RecoveryActionState.SKIPPED
            action.skip_reason = "case expired before execution"
            self._resolve(case, RecoveryResolution.EXPIRED)
            self.session.flush()
            return PipelineResult(case.id, action.id, case.state, None, False)
        if not self._revalidate(case, action, now):
            action.state = RecoveryActionState.SKIPPED
            action.skip_reason = "policy failed during pre-execution revalidation"
            self._move(case, CaseState.DECIDED, "ACTION_SKIPPED_REVALIDATION", None)
            self.session.flush()
            return PipelineResult(case.id, action.id, case.state, VerdictType.DENY, False)
        if self._is_paid(case):
            action.state = RecoveryActionState.SKIPPED
            action.skip_reason = "paid before execution"
            self._move(case, CaseState.DECIDED, "ACTION_SKIPPED_PAID", None)
            self.session.flush()
            return PipelineResult(case.id, action.id, case.state, VerdictType.ALLOW, True)
        self._move(case, CaseState.EXECUTING, "ACTION_EXECUTING", {"action_id": action.id})
        action.state = RecoveryActionState.EXECUTING
        action.executed_at = now
        ok = self._execute_gateway(case, action)
        action.state = RecoveryActionState.EXECUTED if ok else RecoveryActionState.FAILED
        action.result = {**(action.result if isinstance(action.result, dict) else {}), "succeeded": ok}
        self._move(case, CaseState.VERIFYING, "ACTION_VERIFYING", {"succeeded": ok})
        recovered = self._verify(case, action, ok, continue_on_failure)
        self.session.flush()
        return PipelineResult(case.id, action.id, case.state, VerdictType.ALLOW, recovered)

    def resume_approved(self, approval: HumanApproval, now: datetime | None = None) -> RecoveryAction | None:
        """Revalidate and schedule the original decision after human approval.

        Approval is never a shortcut around the policy gate.  The existing
        decision is retained for auditability and is evaluated again with the
        approval fact before any durable action is created.
        """
        now = now or datetime.now(UTC)
        if approval.decision is not ApprovalDecision.APPROVED:
            raise ValueError("only approved requests can be resumed")
        case = self.session.get(RecoveryCase, approval.case_id)
        decision = self.session.get(RecoveryDecision, approval.decision_id)
        if case is None or decision is None:
            raise LookupError("approval case or decision is missing")
        if case.state is not CaseState.AWAITING_APPROVAL:
            raise ValueError("case is not awaiting approval")

        transition(case.state, CaseState.DECIDED)
        case.state = CaseState.DECIDED
        self.repo.audit("APPROVAL_GRANTED", AuditActor.HUMAN, case.id, {"approval_id": approval.id})
        domain_case = DomainCase(
            case_class=case.case_class,
            amount_at_risk_paise=case.amount_at_risk_paise,
            failure_category=case.failure_category,
            customer_id=case.customer_id,
            order_id=case.order_id,
            subscription_id=case.subscription_id,
            state=case.state,
            contacts_used=case.contacts_used,
            charge_attempts_used=case.charge_attempts_used,
            opened_at=_aware(case.opened_at),
            id=case.id,
        )
        delay = decision.proposed_delay_minutes or 0
        verdict = evaluate(
            domain_case,
            Decision(decision.proposed_action, delay, reason_codes=tuple(decision.reason_codes or [])),
            WorldState(
                now=now,
                consent=self.repo.consent(case.customer_id, ConsentChannel.EMAIL),
                customer_contacts_7d=self.repo.contacts_last_7d(case.customer_id, now),
                paid=self._is_paid(case),
                chargeable=case.recoverability is not Recoverability.NOT_RECOVERABLE,
                rail_degraded=self._rail_degraded(case, now),
                approval_granted=True,
            ),
            self.policy,
        )
        evaluation = self.repo.policy_evaluation(
            decision.id,
            case.id,
            VerdictType(verdict.verdict),
            verdict.final_action,
            [{"rule_id": rule.rule_id, "passed": rule.passed, "detail": rule.detail} for rule in verdict.rules_fired],
            self.policy.config_hash,
        )
        self.repo.audit(
            "APPROVAL_REVALIDATED",
            AuditActor.RULE,
            case.id,
            {"verdict": verdict.verdict, "rules": [rule.rule_id for rule in verdict.rules_fired]},
        )
        if verdict.verdict is not VerdictType.ALLOW or verdict.final_action is None:
            self._resolve(
                case,
                RecoveryResolution.STOPPED
                if verdict.verdict is VerdictType.DENY
                else RecoveryResolution.EXHAUSTED,
            )
            return None

        scheduled_for = now + timedelta(minutes=delay)
        key = hashlib.sha256(
            f"{case.id}:{decision.id}:{verdict.final_action.value}:{scheduled_for.isoformat()}".encode()
        ).hexdigest()
        action = self.repo.action(
            case_id=case.id,
            policy_evaluation_id=evaluation.id,
            action_type=verdict.final_action,
            idempotency_key=key,
            scheduled_for=scheduled_for,
        )
        self._move(case, CaseState.SCHEDULED, "ACTION_SCHEDULED_AFTER_APPROVAL", {"action_id": action.id})
        self.session.flush()
        return action

    def _execute_gateway(self, case: RecoveryCase, action: RecoveryAction) -> bool:
        if hasattr(self.gateway, "execute_case"):
            if action.action_type is ActionType.CREATE_PAYMENT_LINK:
                link = self.gateway.create_payment_link(
                    case.id,
                    case.amount_at_risk_paise,
                    action.scheduled_for + timedelta(days=1),
                    action.idempotency_key,
                )
                action.result = {"payment_link": link}
            if action.action_type in {ActionType.SEND_REMINDER, ActionType.SUGGEST_ALTERNATE_METHOD}:
                link = getattr(self.gateway, "links", {}).get(case.id, {})
                rendered = render_payment_reminder(
                    case.amount_at_risk_paise,
                    str(link.get("short_url", "payment portal")),
                )
                self.repo.message(
                    case.id,
                    action.id,
                    MessageChannel.EMAIL,
                    "payment_reminder",
                    rendered["body"],
                    rendered["subject"],
                )
            return bool(self.gateway.execute_case(case, action.action_type, action.idempotency_key))
        if action.action_type is ActionType.RETRY_MANDATE_CHARGE and case.subscription_id:
            result = self.gateway.charge_mandate(case.subscription_id, case.amount_at_risk_paise, action.idempotency_key)
            return result.status is PaymentAttemptStatus.CAPTURED
        if action.action_type is ActionType.CREATE_PAYMENT_LINK:
            link = self.gateway.create_payment_link(
                case.id,
                case.amount_at_risk_paise,
                action.scheduled_for + timedelta(days=1),
                action.idempotency_key,
            )
            action.result = {"payment_link": link}
            return True
        return False

    def _verify(
        self,
        case: RecoveryCase,
        action: RecoveryAction,
        ok: bool,
        continue_on_failure: bool = False,
    ) -> bool:
        if ok and self._gateway_readback_paid(case):
            attempt = self.repo.payment_attempt(
                order_id=case.order_id,
                subscription_id=case.subscription_id,
                amount_paise=case.amount_at_risk_paise,
                status=PaymentAttemptStatus.CAPTURED,
                provider_payment_id=f"recovery:{action.id}",
                initiated_by=InitiatedBy.RECOVERY_SYSTEM,
            )
            self._mark_paid(case.order_id)
            case.recovered_amount_paise = case.amount_at_risk_paise
            case.recovered_attempt_id = attempt.id
            case.resolution = RecoveryResolution.RECOVERED
            case.resolved_at = datetime.now(UTC)
            transition(case.state, CaseState.RECOVERED)
            case.state = CaseState.RECOVERED
            self.repo.audit("RECOVERY_VERIFIED", AuditActor.GATEWAY, case.id, {"action_id": action.id})
            self._check_duplicate_charges(case)
            return True
        if ok and action.action_type is ActionType.CREATE_PAYMENT_LINK:
            transition(case.state, CaseState.DECIDED)
            case.state = CaseState.DECIDED
            self.repo.audit("PAYMENT_LINK_CREATED_AWAITING_PAYMENT", AuditActor.GATEWAY, case.id, {"action_id": action.id})
            return False
        if REGISTRY[action.action_type].consumes_charge_budget:
            case.charge_attempts_used += 1
        if REGISTRY[action.action_type].consumes_contact_budget:
            case.contacts_used += 1
        if continue_on_failure:
            transition(case.state, CaseState.DECIDED)
            case.state = CaseState.DECIDED
            self.repo.audit("ACTION_FAILED_REASSESS", AuditActor.SYSTEM, case.id, {"action_id": action.id})
        else:
            self._resolve(case, RecoveryResolution.EXHAUSTED)
        return False

    def exhaust(self, case: RecoveryCase) -> None:
        """Resolve a case after a finite strategy has used all of its attempts."""
        if case.state is CaseState.DECIDED:
            self._resolve(case, RecoveryResolution.EXHAUSTED)
            self.session.flush()

    def _revalidate(self, case: RecoveryCase, action: RecoveryAction, now: datetime) -> bool:
        domain_case = DomainCase(
            case_class=case.case_class,
            amount_at_risk_paise=case.amount_at_risk_paise,
            failure_category=case.failure_category,
            customer_id=case.customer_id,
            order_id=case.order_id,
            subscription_id=case.subscription_id,
            state=CaseState.SCHEDULED,
            contacts_used=case.contacts_used,
            charge_attempts_used=case.charge_attempts_used,
            opened_at=_aware(case.opened_at),
            id=case.id,
        )
        result = evaluate(
            domain_case,
            Decision(action.action_type),
            WorldState(
                now=now,
                consent=self.repo.consent(case.customer_id, ConsentChannel.EMAIL),
                customer_contacts_7d=self.repo.contacts_last_7d(case.customer_id, now),
                paid=self._is_paid(case),
                chargeable=case.recoverability.value != "NOT_RECOVERABLE",
                rail_degraded=self._rail_degraded(case, now),
                approval_granted=bool(
                    self.session.scalar(
                        select(HumanApproval).where(
                            HumanApproval.case_id == case.id,
                            HumanApproval.decision == ApprovalDecision.APPROVED,
                        )
                    )
                ),
            ),
            self.policy,
        )
        if result.verdict is not VerdictType.ALLOW:
            self.repo.audit("REVALIDATION_DENIED", AuditActor.RULE, case.id, {"verdict": result.verdict})
            return False
        return True

    def _gateway_readback_paid(self, case: RecoveryCase) -> bool:
        for order in getattr(self.gateway, "orders", {}).values():
            if order.customer_id == case.customer_id and order.status.value == "PAID":
                return True
        return self._is_paid(case)

    def _check_duplicate_charges(self, case: RecoveryCase) -> None:
        statement = select(PaymentAttempt).where(
            PaymentAttempt.order_id == case.order_id,
            PaymentAttempt.status == PaymentAttemptStatus.CAPTURED,
        )
        if len(list(self.session.scalars(statement))) > 1:
            self.repo.audit(
                "DUPLICATE_CHARGE_COMPENSATION_REQUIRED",
                AuditActor.SYSTEM,
                case.id,
                {"compensation": "REFUND_REVIEW"},
            )

    def expire_payment_link(self, action_id: str) -> None:
        action = self.session.get(RecoveryAction, action_id)
        if action is None:
            raise LookupError(action_id)
        if action.action_type is not ActionType.CREATE_PAYMENT_LINK:
            raise ValueError("only payment-link actions can expire")
        action.state = RecoveryActionState.SKIPPED
        action.skip_reason = "payment link expired"
        case = self.session.get(RecoveryCase, action.case_id)
        if case and case.state not in {CaseState.RECOVERED, CaseState.EXHAUSTED, CaseState.STOPPED, CaseState.EXPIRED}:
            self._resolve(case, RecoveryResolution.EXPIRED)
        self.repo.audit("PAYMENT_LINK_EXPIRED_COMPENSATED", AuditActor.SYSTEM, action.case_id)

    def _category(self, event: NormalizedEvent) -> FailureCategory:
        if event.payment and event.payment.error_code:
            try:
                from backend.domain.enums import FailureCategory
                return FailureCategory(event.payment.error_code)
            except ValueError:
                return map_error(event.payment.error_code)
        from backend.domain.enums import FailureCategory
        return FailureCategory.UNKNOWN

    def _move(self, case: RecoveryCase, target: CaseState, event: str, payload: dict[str, Any] | None) -> None:
        transition(case.state, target)
        case.state = target
        self.repo.audit(event, AuditActor.SYSTEM, case.id, payload)

    def _resolve(self, case: RecoveryCase, resolution: RecoveryResolution) -> None:
        target = CaseState(resolution.value)
        if case.state not in {CaseState.RECOVERED, CaseState.EXHAUSTED, CaseState.STOPPED, CaseState.EXPIRED}:
            if target is not case.state:
                transition(case.state, target)
            case.state = target
        case.resolution = resolution
        case.resolved_at = datetime.now(UTC)
        self.repo.audit("CASE_RESOLVED", AuditActor.SYSTEM, case.id, {"resolution": resolution.value})

    def _mark_paid(self, order_id: str | None) -> None:
        if order_id:
            from backend.db.models import Order
            order = self.session.get(Order, order_id)
            if order:
                from backend.domain.enums import OrderStatus
                order.status = OrderStatus.PAID

    def _is_paid(self, case: RecoveryCase) -> bool:
        if not case.order_id:
            return False
        from backend.db.models import Order
        from backend.domain.enums import OrderStatus
        order = self.session.get(Order, case.order_id)
        return bool(order and order.status is OrderStatus.PAID)

    def _rail_degraded(self, case: RecoveryCase, now: datetime) -> bool:
        statement = select(PaymentAttempt.method).where(
            (PaymentAttempt.order_id == case.order_id)
            if case.order_id
            else (PaymentAttempt.subscription_id == case.subscription_id)
        ).order_by(PaymentAttempt.occurred_at.desc())
        method = self.session.scalar(statement)
        issuer_or_bank = self.session.scalar(
            select(PaymentAttempt.issuer_or_bank).where(
                (PaymentAttempt.order_id == case.order_id)
                if case.order_id
                else (PaymentAttempt.subscription_id == case.subscription_id)
            ).order_by(PaymentAttempt.occurred_at.desc())
        )
        return self.repo.outage_signal(
            method,
            now,
            int(self.policy.values["outage_window_minutes"]),
            int(self.policy.values["outage_min_attempts"]),
            float(self.policy.values["outage_failure_multiplier"]),
            issuer_or_bank,
        )


__all__ = ["Orchestrator", "PipelineResult"]
