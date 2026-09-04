"""Deterministic eligible-action generation, before the safety policy gate."""

from backend.domain.enums import ActionType, CaseClass, FailureCategory
from backend.domain.models import RecoveryCase

TRANSIENT = {
    FailureCategory.TEMPORARY_GATEWAY_ERROR,
    FailureCategory.TEMPORARY_BANK_ERROR,
    FailureCategory.INSUFFICIENT_FUNDS,
}


def eligible_actions(case: RecoveryCase) -> tuple[ActionType, ...]:
    if case.case_class is CaseClass.A_MANDATE:
        if case.failure_category in TRANSIENT:
            return (ActionType.RETRY_MANDATE_CHARGE, ActionType.RESCHEDULE_MANDATE_CHARGE, ActionType.ESCALATE_TO_HUMAN)
        return (ActionType.ESCALATE_TO_HUMAN, ActionType.STOP)
    if case.failure_category in {FailureCategory.CUSTOMER_CANCELLED, FailureCategory.MANDATE_INVALID}:
        return (ActionType.STOP,)
    return (
        ActionType.CREATE_PAYMENT_LINK,
        ActionType.SEND_REMINDER,
        ActionType.SUGGEST_ALTERNATE_METHOD,
        ActionType.WAIT,
        ActionType.STOP,
    )


def first_eligible(case: RecoveryCase) -> tuple[ActionType, list[str]]:
    actions = eligible_actions(case)
    return actions[0], [f"ELIGIBLE_{actions[0].value}"]


__all__ = ["eligible_actions", "first_eligible"]
