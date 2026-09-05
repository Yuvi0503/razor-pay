"""Evaluation adapter that drives scenarios through the production pipeline."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.db.base import Base
from backend.domain.contracts import (
    NormalizedEvent,
    OrderSnapshot,
    PaymentSnapshot,
    SubscriptionSnapshot,
)
from backend.domain.enums import (
    ActionType,
    ClassifiedBy,
    DecisionSource,
    FailureCategory,
    OrderStatus,
    PaymentAttemptStatus,
)
from backend.domain.models import RecoveryCase as DomainCase
from backend.llm.advisor import AdvisorResult, LLMAdvisor
from backend.orchestration.orchestrator import Orchestrator, PipelineResult
from backend.policy.config_loader import PolicyConfig
from backend.policy.rules import eligible_actions
from sim.gateway import SimulatedGateway
from sim.scenarios import Scenario


def run_scenario(
    scenario: Scenario,
    arm: str,
    seed: int,
    policy: PolicyConfig,
    gateway: SimulatedGateway,
    session: Session,
    advisor: LLMAdvisor | None = None,
    auto_approve: bool = True,
) -> PipelineResult:
    now = datetime(2026, 1, 1, 4, tzinfo=UTC)  # 09:30 IST, inside the contact window
    gateway.register(scenario, now)
    order = OrderSnapshot(
        order_id=f"order_{scenario.key}",
        amount_paise=scenario.amount_paise,
        currency="INR",
        status=OrderStatus.ATTEMPTED,
        customer_id=f"customer_{scenario.key}",
        created_at=now - timedelta(hours=scenario.payment_age_hours),
    )
    subscription = None
    if scenario.case_class.value == "A_MANDATE":
        subscription = SubscriptionSnapshot(
            subscription_id=f"sub_{scenario.key}",
            customer_id=order.customer_id,
            amount_paise=scenario.amount_paise,
            status="active",
            mandate_active=True,
            next_charge_at=now + timedelta(days=1),
        )
    event = NormalizedEvent(
        provider_event_id=f"evt_{scenario.key}",
        event_type="payment.failed",
        received_at=now,
        merchant_id="merchant-demo",
        customer_id=order.customer_id,
        order_id=order.order_id,
        subscription_id=subscription.subscription_id if subscription else None,
        order=order,
        subscription=subscription,
        payment=PaymentSnapshot(
            payment_id=f"payment_{scenario.key}_initial",
            amount_paise=scenario.amount_paise,
            status=PaymentAttemptStatus.FAILED,
            method=scenario.method,
            issuer_or_bank=scenario.issuer_or_bank,
            order_id=order.order_id,
            subscription_id=subscription.subscription_id if subscription else None,
            error_code=scenario.failure_category.value,
            error_reason=scenario.failure_category.value,
        ),
    )
    orchestrator = Orchestrator(session, gateway, policy)
    classification = None
    if advisor is not None and scenario.failure_category is FailureCategory.UNKNOWN:
        classification = advisor.classify(
            {
                "case_class": scenario.case_class.value,
                "failure_category": scenario.failure_category.value,
                "amount_paise": scenario.amount_paise,
                "notes": scenario.notes,
            }
        )
    case = (
        orchestrator.ingest_stale_order("merchant-demo", order, event.provider_event_id, arm)
        if scenario.case_class.value == "C_ABANDONED"
        else orchestrator.ingest(
            event,
            arm,
            failure_category_override=(classification.classification.category if classification else None),
            classified_by=(ClassifiedBy.LLM if classification and classification.source == "LLM" else ClassifiedBy.RULE),
        )
    )
    if case is None:
        raise RuntimeError("scenario did not create a recovery case")
    advisor_result = _candidate_result(arm, scenario, policy, advisor)
    selected = None if arm == "control" else (
        advisor_result.decision.action
        if advisor_result is not None
        else _candidate(arm, scenario, seed, policy, advisor)
    )
    if selected is None:
        selected = ActionType.WAIT
    if arm == "naive":
        result = None
        for attempt, delay in enumerate((60, 24 * 60, 72 * 60)):
            result = orchestrator.process(
                case,
                now=now,
                auto_approve=True,
                candidate_action=selected,
                delay_minutes=delay,
                execute_immediately=True,
                continue_on_failure=attempt < 2,
            )
            if result.recovered:
                break
        if result is None:
            raise RuntimeError("naive schedule did not run")
        if case.state.value == "DECIDED":
            orchestrator.exhaust(case)
            result = PipelineResult(result.case_id, result.action_id, case.state, result.verdict, False)
    else:
        result = orchestrator.process(
            case,
            now=now,
            auto_approve=auto_approve,
            candidate_action=selected,
        execute_immediately=True,
        decision_source=(DecisionSource.LLM if advisor_result and advisor_result.source == "LLM" else DecisionSource.RULE),
        llm_decision=(advisor_result.decision if advisor_result and advisor_result.source == "LLM" else None),
        llm_model=(advisor.model if advisor_result and advisor is not None else None),
        llm_prompt_version=(advisor.prompt_version if advisor_result and advisor is not None else None),
        llm_cache_key=(advisor_result.cache_key if advisor_result else None),
        llm_fallback_reason=(advisor_result.fallback_reason if advisor_result else None),
        llm_raw_response=(advisor_result.raw_response if advisor_result and advisor_result.source == "LLM" else None),
        llm_latency_ms=(advisor_result.latency_ms if advisor_result and advisor_result.source == "LLM" else None),
        decision_input_snapshot=(
            {
                "case_class": scenario.case_class.value,
                "failure_category": scenario.failure_category.value,
                "amount_paise": scenario.amount_paise,
                "notes": scenario.notes,
            }
            if advisor_result
            else None
        ),
        decision_reason_codes=(
            [code.value for code in advisor_result.decision.reason_codes]
            if advisor_result and advisor_result.source == "RULE"
            else None
        ),
    )
    return result


def _candidate(
    arm: str,
    scenario: Scenario,
    seed: int,
    policy: PolicyConfig,
    advisor: LLMAdvisor | None = None,
) -> ActionType:
    result = _candidate_result(arm, scenario, policy, advisor)
    if result is not None:
        return result.decision.action
    from eval.arms import choose

    selected = choose("rules" if arm == "rules_llm" else arm, scenario, policy, seed)
    return selected or ActionType.WAIT


def _candidate_result(
    arm: str, scenario: Scenario, policy: PolicyConfig, advisor: LLMAdvisor | None
) -> AdvisorResult | None:
    if arm != "rules_llm":
        return None
    advisor = advisor or LLMAdvisor.from_environment()
    case = DomainCase(scenario.case_class, scenario.amount_paise, scenario.failure_category)
    eligible = eligible_actions(case)
    from eval.arms import choose

    deterministic_fallback = choose("rules", scenario, policy, 0) or eligible[0]
    return advisor.decide(
        {
            "case_class": scenario.case_class.value,
            "failure_category": scenario.failure_category.value,
            "amount_paise": scenario.amount_paise,
            "notes": scenario.notes,
        },
        eligible,
        deterministic_fallback,
    )


def new_run(policy: PolicyConfig) -> tuple[Session, SimulatedGateway]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)(), SimulatedGateway(0)


__all__ = ["new_run", "run_scenario"]
