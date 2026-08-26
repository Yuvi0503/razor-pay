from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from .enums import ActionType, CaseClass, CaseState, ConsentState, FailureCategory


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class RecoveryCase:
    case_class: CaseClass
    amount_at_risk_paise: int
    failure_category: FailureCategory
    customer_id: str = "customer"
    order_id: str | None = None
    subscription_id: str | None = None
    state: CaseState = CaseState.OPEN
    contacts_used: int = 0
    charge_attempts_used: int = 0
    opened_at: datetime = field(default_factory=utcnow)
    last_action_at: datetime | None = None
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True, slots=True)
class Decision:
    action: ActionType
    delay_minutes: int = 0
    source: str = "RULE"
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorldState:
    now: datetime
    consent: ConsentState = ConsentState.UNKNOWN
    customer_contacts_7d: int = 0
    paid: bool = False
    chargeable: bool = True
    rail_degraded: bool = False
    template_dlt_registered: bool = True


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule_id: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PolicyVerdict:
    verdict: str
    final_action: ActionType | None
    rules_fired: tuple[RuleResult, ...]
