from copy import deepcopy
from datetime import UTC, datetime, timedelta

from backend.domain.enums import (
    ActionType,
    CaseClass,
    CaseState,
    ConsentState,
    FailureCategory,
    VerdictType,
)
from backend.domain.models import Decision, RecoveryCase, WorldState
from backend.policy.config_loader import load
from backend.policy.engine import evaluate

NOW = datetime(2026, 1, 1, 10, tzinfo=UTC)


def policy_case(
    *,
    case_class: CaseClass = CaseClass.B_ONEOFF,
    amount_paise: int = 99900,
    state=None,
    contacts_used: int = 0,
    charge_attempts_used: int = 0,
    opened_at: datetime = NOW,
    last_action_at: datetime | None = None,
) -> RecoveryCase:
    kwargs = {
        "contacts_used": contacts_used,
        "charge_attempts_used": charge_attempts_used,
        "opened_at": opened_at,
        "last_action_at": last_action_at,
    }
    if state is not None:
        kwargs["state"] = state
    return RecoveryCase(case_class, amount_paise, FailureCategory.INSUFFICIENT_FUNDS, **kwargs)


def rule_ids(result) -> list[str]:
    return [item.rule_id for item in result.rules_fired]


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


def test_demo_contact_and_approval_defaults_are_safe() -> None:
    values = load().values
    assert values["approved_contact_channels"] == ["EMAIL"]
    assert values["approval_queue_mode"] == "MANUAL_UI"
    assert values["payment_link"] == {
        "expiry_hours": 24,
        "notify_email": False,
        "notify_sms": False,
        "reminder_enable": False,
    }


def test_p01_denies_action_for_wrong_case_class() -> None:
    result = evaluate(
        policy_case(), Decision(ActionType.RETRY_MANDATE_CHARGE), WorldState(NOW), load()
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result) == ["P01"]


def test_p02_denies_terminal_case() -> None:
    result = evaluate(
        policy_case(state=CaseState.RECOVERED),
        Decision(ActionType.CREATE_PAYMENT_LINK),
        WorldState(NOW),
        load(),
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result) == ["P01", "P02"]


def test_p03_denies_opted_out_contact() -> None:
    result = evaluate(
        policy_case(),
        Decision(ActionType.SEND_REMINDER),
        WorldState(NOW, consent=ConsentState.OPTED_OUT),
        load(),
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result)[-1] == "P03"


def test_p04_denies_exhausted_contact_budget() -> None:
    result = evaluate(
        policy_case(contacts_used=3),
        Decision(ActionType.SEND_REMINDER),
        WorldState(NOW),
        load(),
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result)[-1] == "P04"


def test_p05_denies_exhausted_charge_budget() -> None:
    result = evaluate(
        policy_case(case_class=CaseClass.A_MANDATE, charge_attempts_used=3),
        Decision(ActionType.RETRY_MANDATE_CHARGE),
        WorldState(NOW),
        load(),
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result)[-1] == "P05"


def test_p06_downgrades_during_cooldown() -> None:
    result = evaluate(
        policy_case(last_action_at=NOW - timedelta(minutes=1)),
        Decision(ActionType.CREATE_PAYMENT_LINK),
        WorldState(NOW),
        load(),
    )
    assert result.verdict == VerdictType.DOWNGRADE
    assert result.final_action is ActionType.WAIT
    assert rule_ids(result)[-1] == "P06"


def test_p07_downgrades_contact_outside_ist_window() -> None:
    outside_window = datetime(2026, 1, 1, 2, tzinfo=UTC)  # 07:30 IST
    result = evaluate(
        policy_case(opened_at=outside_window),
        Decision(ActionType.SEND_REMINDER),
        WorldState(outside_window),
        load(),
    )
    assert result.verdict == VerdictType.DOWNGRADE
    assert result.final_action is ActionType.WAIT
    assert rule_ids(result)[-1] == "P07"


def test_p08_requires_human_for_high_value_case() -> None:
    result = evaluate(
        policy_case(amount_paise=1_000_001),
        Decision(ActionType.CREATE_PAYMENT_LINK),
        WorldState(NOW),
        load(),
    )
    assert result.verdict == VerdictType.REQUIRE_HUMAN
    assert result.final_action is None
    assert rule_ids(result)[-1] == "P08"


def test_p09_downgrades_mandate_retry_on_degraded_rail() -> None:
    result = evaluate(
        policy_case(case_class=CaseClass.A_MANDATE),
        Decision(ActionType.RETRY_MANDATE_CHARGE),
        WorldState(NOW, rail_degraded=True),
        load(),
    )
    assert result.verdict == VerdictType.DOWNGRADE
    assert result.final_action is ActionType.WAIT
    assert rule_ids(result)[-1] == "P09"


def test_p10_denies_paid_case() -> None:
    result = evaluate(
        policy_case(),
        Decision(ActionType.CREATE_PAYMENT_LINK),
        WorldState(NOW, paid=True),
        load(),
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result)[-1] == "P10"


def test_p11_denies_unapproved_contact_channel() -> None:
    result = evaluate(
        policy_case(),
        Decision(ActionType.SEND_REMINDER),
        WorldState(NOW, channel="SMS", sms_consent=ConsentState.OPTED_IN),
        load(),
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result)[-1] == "P11"


def test_p12_kill_switch_denies_every_action() -> None:
    policy = load()
    values = deepcopy(policy.values)
    values["kill_switch"] = True
    switched_off = type(policy)(values, policy.config_hash)
    result = evaluate(
        policy_case(), Decision(ActionType.CREATE_PAYMENT_LINK), WorldState(NOW), switched_off
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result) == ["P01", "P02", "P12"]


def test_p13_denies_expired_case() -> None:
    old = NOW - timedelta(hours=169)
    result = evaluate(
        policy_case(opened_at=old),
        Decision(ActionType.CREATE_PAYMENT_LINK),
        WorldState(NOW),
        load(),
    )
    assert result.verdict == VerdictType.DENY
    assert rule_ids(result)[-1] == "P13"


def test_p11_irreversible_action_passes_when_within_automatic_ceiling() -> None:
    result = evaluate(
        policy_case(amount_paise=999900),
        Decision(ActionType.SEND_REMINDER),
        WorldState(NOW),
        load(),
    )
    assert result.verdict == VerdictType.ALLOW
    assert rule_ids(result)[-1] == "P15"


def test_p14_and_p15_are_explicitly_not_verified_and_disabled() -> None:
    result = evaluate(
        policy_case(case_class=CaseClass.A_MANDATE),
        Decision(ActionType.RESCHEDULE_MANDATE_CHARGE),
        WorldState(NOW),
        load(),
    )
    assert result.verdict == VerdictType.ALLOW
    assert [(item.rule_id, item.detail) for item in result.rules_fired[-2:]] == [
        ("P14", "NotVerified: disabled"),
        ("P15", "NotVerified: disabled"),
    ]
