from dataclasses import dataclass

from backend.domain.enums import ActionType, CaseClass


@dataclass(frozen=True, slots=True)
class ActionSpec:
    allowed_classes: frozenset[CaseClass]
    reversible: bool
    consumes_contact_budget: bool = False
    consumes_charge_budget: bool = False


REGISTRY: dict[ActionType, ActionSpec] = {
    ActionType.RETRY_MANDATE_CHARGE: ActionSpec(
        frozenset({CaseClass.A_MANDATE}), False, consumes_charge_budget=True
    ),
    ActionType.RESCHEDULE_MANDATE_CHARGE: ActionSpec(frozenset({CaseClass.A_MANDATE}), True),
    ActionType.CREATE_PAYMENT_LINK: ActionSpec(
        frozenset({CaseClass.B_ONEOFF, CaseClass.C_ABANDONED}), True
    ),
    ActionType.SEND_REMINDER: ActionSpec(frozenset(CaseClass), False, consumes_contact_budget=True),
    ActionType.SUGGEST_ALTERNATE_METHOD: ActionSpec(
        frozenset({CaseClass.B_ONEOFF, CaseClass.C_ABANDONED}), False, consumes_contact_budget=True
    ),
    ActionType.WAIT: ActionSpec(frozenset(CaseClass), True),
    ActionType.ESCALATE_TO_HUMAN: ActionSpec(frozenset(CaseClass), True),
    ActionType.STOP: ActionSpec(frozenset(CaseClass), False),
}
