from backend.domain.enums import ActionType, CaseClass
from backend.domain.models import Decision, RecoveryCase, WorldState
from backend.policy.config_loader import PolicyConfig
from backend.policy.engine import evaluate
from sim.outcome_model import oracle_action
from sim.scenarios import Scenario


def choose(arm: str, scenario: Scenario, cfg: PolicyConfig, seed: int) -> ActionType | None:
    if arm == "control":
        return None
    if arm == "oracle":
        return oracle_action(scenario, seed)
    if arm == "naive":
        return (
            ActionType.RETRY_MANDATE_CHARGE
            if scenario.case_class is CaseClass.A_MANDATE
            else ActionType.SEND_REMINDER
        )
    candidate = (
        ActionType.RETRY_MANDATE_CHARGE
        if scenario.case_class is CaseClass.A_MANDATE
        else ActionType.CREATE_PAYMENT_LINK
    )
    case = RecoveryCase(scenario.case_class, scenario.amount_paise, scenario.failure_category)
    verdict = evaluate(case, Decision(candidate), WorldState(now=case.opened_at), cfg)
    return verdict.final_action if verdict.verdict == "ALLOW" else ActionType.WAIT
