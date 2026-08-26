from dataclasses import asdict, dataclass
from random import Random

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


def generate(count: int, seed: int) -> list[Scenario]:
    rng = Random(seed)
    categories = [
        FailureCategory.INSUFFICIENT_FUNDS,
        FailureCategory.TEMPORARY_BANK_ERROR,
        FailureCategory.AUTHENTICATION_FAILED,
        FailureCategory.UNKNOWN,
    ]
    output = []
    for index in range(count):
        cls = CaseClass.A_MANDATE if index % 3 == 0 else CaseClass.B_ONEOFF
        category = categories[index % len(categories)]
        output.append(
            Scenario(
                key=f"scenario-{index:05d}",
                case_class=cls,
                failure_category=category,
                amount_paise=rng.choice([99900, 249900, 750000, 1250000]),
                organic_probability=round(rng.uniform(0.04, 0.20), 3),
                recovery_probability=round(rng.uniform(0.20, 0.65), 3),
                notes="Customer contacted support; retry after salary date."
                if index % 7 == 0
                else "",
            )
        )
    return output


def canonical(scenarios: list[Scenario]) -> list[dict]:
    return [asdict(item) for item in scenarios]
