from datetime import UTC, datetime

from backend.domain.enums import (
    ActionType,
    CaseClass,
    ConsentState,
    FailureCategory,
    VerdictType,
)
from backend.domain.models import Decision, RecoveryCase, WorldState
from backend.policy.config_loader import load
from backend.policy.engine import evaluate


def case(
    *,
    case_class: CaseClass = CaseClass.B_ONEOFF,
    contacts_used: int = 0,
    charge_attempts_used: int = 0,
) -> RecoveryCase:
    return RecoveryCase(
        case_class=case_class,
        amount_at_risk_paise=99900,
        failure_category=FailureCategory.INSUFFICIENT_FUNDS,
        contacts_used=contacts_used,
        charge_attempts_used=charge_attempts_used,
    )


def evaluate_contact(
    *,
    now: datetime,
    contacts_used: int = 0,
    customer_contacts_7d: int = 0,
    channel: str = "EMAIL",
    sms_consent: ConsentState = ConsentState.UNKNOWN,
) -> object:
    return evaluate(
        case(contacts_used=contacts_used),
        Decision(ActionType.SEND_REMINDER),
        WorldState(
            now,
            consent=ConsentState.UNKNOWN,
            customer_contacts_7d=customer_contacts_7d,
            channel=channel,
            sms_consent=sms_consent,
        ),
        load(),
    )


def test_contact_budget_allows_values_below_both_limits() -> None:
    result = evaluate_contact(
        now=datetime(2026, 1, 1, 4, tzinfo=UTC),
        contacts_used=2,
        customer_contacts_7d=4,
    )
    assert result.verdict is VerdictType.ALLOW
    assert result.final_action is ActionType.SEND_REMINDER


def test_per_case_contact_budget_denies_at_limit() -> None:
    result = evaluate_contact(
        now=datetime(2026, 1, 1, 4, tzinfo=UTC),
        contacts_used=3,
        customer_contacts_7d=0,
    )
    assert result.verdict is VerdictType.DENY
    assert result.rules_fired[-1].rule_id == "P04"
    assert result.rules_fired[-1].passed is False


def test_per_customer_seven_day_contact_budget_denies_at_limit() -> None:
    result = evaluate_contact(
        now=datetime(2026, 1, 1, 4, tzinfo=UTC),
        contacts_used=0,
        customer_contacts_7d=5,
    )
    assert result.verdict is VerdictType.DENY
    assert result.rules_fired[-1].rule_id == "P04"
    assert result.rules_fired[-1].passed is False


def test_charge_budget_allows_attempt_below_limit() -> None:
    result = evaluate(
        case(case_class=CaseClass.A_MANDATE, charge_attempts_used=2),
        Decision(ActionType.RETRY_MANDATE_CHARGE),
        WorldState(datetime(2026, 1, 1, 4, tzinfo=UTC)),
        load(),
    )
    assert result.verdict is VerdictType.ALLOW
    assert result.final_action is ActionType.RETRY_MANDATE_CHARGE


def test_charge_budget_denies_attempt_at_limit() -> None:
    result = evaluate(
        case(case_class=CaseClass.A_MANDATE, charge_attempts_used=3),
        Decision(ActionType.RETRY_MANDATE_CHARGE),
        WorldState(datetime(2026, 1, 1, 4, tzinfo=UTC)),
        load(),
    )
    assert result.verdict is VerdictType.DENY
    assert result.rules_fired[-1].rule_id == "P05"
    assert result.rules_fired[-1].passed is False


def test_contact_is_allowed_at_exact_09_00_ist() -> None:
    nine_am_ist = datetime(2026, 1, 1, 3, 30, tzinfo=UTC)
    result = evaluate_contact(now=nine_am_ist)
    assert result.verdict is VerdictType.ALLOW
    assert any(item.rule_id == "P07" and item.passed for item in result.rules_fired)


def test_contact_is_allowed_before_exact_20_00_ist() -> None:
    seven_thirty_pm_ist = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
    result = evaluate_contact(now=seven_thirty_pm_ist)
    assert result.verdict is VerdictType.ALLOW
    assert any(item.rule_id == "P07" and item.passed for item in result.rules_fired)


def test_contact_is_downgraded_before_09_00_ist() -> None:
    eight_thirty_am_ist = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    result = evaluate_contact(now=eight_thirty_am_ist)
    assert result.verdict is VerdictType.DOWNGRADE
    assert result.final_action is ActionType.WAIT
    assert result.rules_fired[-1].rule_id == "P07"
    assert result.rules_fired[-1].passed is False


def test_contact_is_downgraded_at_exact_20_00_ist() -> None:
    eight_pm_ist = datetime(2026, 1, 1, 14, 30, tzinfo=UTC)
    result = evaluate_contact(now=eight_pm_ist)
    assert result.verdict is VerdictType.DOWNGRADE
    assert result.final_action is ActionType.WAIT
    assert result.rules_fired[-1].rule_id == "P07"
    assert result.rules_fired[-1].passed is False


def test_sms_is_rejected_when_email_is_the_only_approved_channel() -> None:
    result = evaluate_contact(
        now=datetime(2026, 1, 1, 4, tzinfo=UTC),
        channel="SMS",
        sms_consent=ConsentState.OPTED_IN,
    )
    assert result.verdict is VerdictType.DENY
    assert result.rules_fired[-1].rule_id == "P11"
    assert result.rules_fired[-1].passed is False
