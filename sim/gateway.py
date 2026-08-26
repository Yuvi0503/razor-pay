from dataclasses import dataclass

from backend.domain.enums import ActionType

from .outcome_model import succeeds
from .scenarios import Scenario


@dataclass(slots=True)
class SimulatedGateway:
    seed: int

    def execute(self, scenario: Scenario, action: ActionType | None) -> bool:
        return succeeds(scenario, action, self.seed)
