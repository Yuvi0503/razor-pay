"""Hidden evaluator truth. Importable only by sim.gateway/eval oracle."""

from random import Random

from backend.domain.enums import ActionType

from .scenarios import Scenario


def succeeds(scenario: Scenario, action: ActionType | None, seed: int) -> bool:
    rng = Random(f"{seed}:{scenario.key}:{action}")
    probability = scenario.organic_probability if action is None else scenario.recovery_probability
    if action in {ActionType.WAIT, ActionType.STOP}:
        probability = scenario.organic_probability
    if action is ActionType.RETRY_MANDATE_CHARGE and scenario.case_class.value != "A_MANDATE":
        probability = 0
    return rng.random() < probability


def oracle_action(scenario: Scenario, seed: int) -> ActionType | None:
    options = [
        None,
        ActionType.RETRY_MANDATE_CHARGE,
        ActionType.CREATE_PAYMENT_LINK,
        ActionType.SEND_REMINDER,
    ]
    wins = [item for item in options if succeeds(scenario, item, seed)]
    return wins[0] if wins else None
