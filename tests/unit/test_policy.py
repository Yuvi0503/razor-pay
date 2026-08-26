from datetime import UTC, datetime

from backend.domain.enums import ActionType, CaseClass, ConsentState, FailureCategory
from backend.domain.models import Decision, RecoveryCase, WorldState
from backend.policy.config_loader import load
from backend.policy.engine import evaluate


def test_mandate_retry_is_denied_for_one_off() -> None:
    case = RecoveryCase(CaseClass.B_ONEOFF, 99900, FailureCategory.INSUFFICIENT_FUNDS)
    result = evaluate(
        case, Decision(ActionType.RETRY_MANDATE_CHARGE), WorldState(datetime.now(UTC)), load()
    )
    assert result.verdict == "DENY"
    assert result.rules_fired[0].rule_id == "P01"


def test_opted_out_customer_is_never_contacted() -> None:
    case = RecoveryCase(CaseClass.B_ONEOFF, 99900, FailureCategory.INSUFFICIENT_FUNDS)
    result = evaluate(
        case,
        Decision(ActionType.SEND_REMINDER),
        WorldState(datetime.now(UTC), consent=ConsentState.OPTED_OUT),
        load(),
    )
    assert result.verdict == "DENY"
