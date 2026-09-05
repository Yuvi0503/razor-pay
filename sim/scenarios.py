from dataclasses import asdict, dataclass
from random import Random

import yaml

from backend.configuration import config_path
from backend.domain.enums import CaseClass, FailureCategory


@dataclass(frozen=True, slots=True)
class Scenario:
    key: str
    case_class: CaseClass
    failure_category: FailureCategory
    amount_paise: int
    organic_probability: float
    recovery_probability: float
    notes: str
    method: str = "upi"
    issuer_or_bank: str = "sim-bank"
    organic_payer: bool = False
    payment_age_hours: int = 2


def generate(count: int, seed: int) -> list[Scenario]:
    rng = Random(seed)
    config = yaml.safe_load(config_path("sim/scenarios.yaml").read_text()) or {}
    categories = [FailureCategory(value) for value in config.get("failure_categories", [
        FailureCategory.INSUFFICIENT_FUNDS.value,
        FailureCategory.TEMPORARY_BANK_ERROR.value,
        FailureCategory.AUTHENTICATION_FAILED.value,
        FailureCategory.UNKNOWN.value,
    ])]
    amount_options = config.get("amount_paise_options", [99900, 249900, 750000, 1250000])
    organic_low, organic_high = config.get("organic_probability_range", [0.04, 0.20])
    recovery_low, recovery_high = config.get("recovery_probability_range", [0.20, 0.65])
    output = []
    for index in range(count):
        if index % 5 == 2:
            cls = CaseClass.C_ABANDONED
        else:
            cls = CaseClass.A_MANDATE if index % 3 == 0 else CaseClass.B_ONEOFF
        category = categories[index % len(categories)]
        output.append(
            Scenario(
                key=f"scenario-{index:05d}",
                case_class=cls,
                failure_category=category,
                amount_paise=rng.choice(amount_options),
                organic_probability=round(rng.uniform(organic_low, organic_high), 3),
                recovery_probability=round(rng.uniform(recovery_low, recovery_high), 3),
                notes="Customer contacted support; retry after salary date."
                if index % 7 == 0
                else "",
                method="upi" if index % 4 else "card",
                issuer_or_bank=f"sim-bank-{index % 3}",
                organic_payer=index % 11 == 0,
                payment_age_hours=2 + index % 72,
            )
        )
    return output


def canonical(scenarios: list[Scenario]) -> list[dict[str, object]]:
    return [asdict(item) for item in scenarios]
