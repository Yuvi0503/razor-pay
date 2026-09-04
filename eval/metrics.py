from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ArmMetrics:
    arm: str
    cases: int
    recovered_cases: int
    gross_recovered_paise: int
    recovery_rate: float

    def json(self) -> dict[str, Any]:
        return asdict(self)
