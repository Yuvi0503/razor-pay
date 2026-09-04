from datetime import timedelta
from zoneinfo import ZoneInfo

from backend.actions.registry import REGISTRY
from backend.domain.enums import ActionType, CaseState, ConsentState, VerdictType
from backend.domain.models import Decision, PolicyVerdict, RecoveryCase, RuleResult, WorldState

from .config_loader import PolicyConfig

CONTACT_ACTIONS = {ActionType.SEND_REMINDER, ActionType.SUGGEST_ALTERNATE_METHOD}


def evaluate(
    case: RecoveryCase, decision: Decision, world: WorldState, policy: PolicyConfig
) -> PolicyVerdict:
    cfg, results = policy.values, []

    def check(rule: str, passed: bool, detail: str) -> bool:
        results.append(RuleResult(rule, passed, detail))
        return passed

    spec = REGISTRY[decision.action]
    if not check("P01", case.case_class in spec.allowed_classes, "action class allowlist"):
        return PolicyVerdict(VerdictType.DENY, None, tuple(results))
    if not check(
        "P02",
        case.state
        not in {CaseState.RECOVERED, CaseState.EXHAUSTED, CaseState.STOPPED, CaseState.EXPIRED},
        "case is active",
    ):
        return PolicyVerdict(VerdictType.DENY, None, tuple(results))
    if not check("P12", not cfg["kill_switch"], "global kill switch"):
        return PolicyVerdict(VerdictType.DENY, None, tuple(results))
    if decision.action in CONTACT_ACTIONS:
        if not check(
            "P03", world.consent is not ConsentState.OPTED_OUT, "customer has not opted out"
        ):
            return PolicyVerdict(VerdictType.DENY, None, tuple(results))
        if not check(
            "P04",
            case.contacts_used < cfg["max_contacts_per_case"]
            and world.customer_contacts_7d < cfg["max_contacts_per_customer_7d"],
            "contact budget",
        ):
            return PolicyVerdict(VerdictType.DENY, None, tuple(results))
        if not check(
            "P11",
            world.channel in set(cfg.get("approved_contact_channels", ["EMAIL"])),
            "contact channel is merchant-approved",
        ):
            return PolicyVerdict(VerdictType.DENY, None, tuple(results))
        if world.channel == "SMS" and not check(
            "P03_SMS", world.sms_consent is ConsentState.OPTED_IN, "SMS requires opt-in"
        ):
            return PolicyVerdict(VerdictType.DENY, None, tuple(results))
        local = world.now.astimezone(ZoneInfo("Asia/Kolkata")).time()
        start_h, end_h = (int(v.split(":")[0]) for v in cfg["communication_window_ist"])
        if not check("P07", start_h <= local.hour < end_h, "communication window"):
            return PolicyVerdict(VerdictType.DOWNGRADE, ActionType.WAIT, tuple(results))
    if spec.consumes_charge_budget and not check(
        "P05", case.charge_attempts_used < cfg["max_charge_attempts"], "charge budget"
    ):
        return PolicyVerdict(VerdictType.DENY, None, tuple(results))
    if case.last_action_at and not check(
        "P06",
        world.now - case.last_action_at >= timedelta(minutes=cfg["min_gap_minutes"]),
        "cooldown",
    ):
        return PolicyVerdict(VerdictType.DOWNGRADE, ActionType.WAIT, tuple(results))
    if case.amount_at_risk_paise > cfg["auto_ceiling_paise"] and not world.approval_granted:
        check("P08", False, "amount requires human approval")
        return PolicyVerdict(VerdictType.REQUIRE_HUMAN, None, tuple(results))
    if spec.consumes_charge_budget and world.rail_degraded:
        check("P09", False, "target rail is degraded")
        return PolicyVerdict(VerdictType.DOWNGRADE, ActionType.WAIT, tuple(results))
    if not check("P10", world.chargeable and not world.paid, "payment remains actionable"):
        return PolicyVerdict(VerdictType.DENY, None, tuple(results))
    if not check(
        "P13", world.now - case.opened_at <= timedelta(hours=cfg["max_case_age_hours"]), "case age"
    ):
        return PolicyVerdict(VerdictType.DENY, None, tuple(results))
    if not check(
        "P11",
        spec.reversible or case.amount_at_risk_paise <= cfg["auto_ceiling_paise"] or world.approval_granted,
        "irreversible action is within automatic ceiling",
    ):
        return PolicyVerdict(VerdictType.REQUIRE_HUMAN, None, tuple(results))
    if cfg["regulatory_retry_cap"]["enabled"] is False:
        check("P14", True, "NotVerified: disabled")
    if cfg["pre_debit_notice"]["enabled"] is False:
        check("P15", True, "NotVerified: disabled")
    return PolicyVerdict(VerdictType.ALLOW, decision.action, tuple(results))
