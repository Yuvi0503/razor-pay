"""Phase 3 evaluation harness and machine-readable metric assembly."""

import hashlib
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import select

from backend.configuration import config_path
from backend.db.models import (
    AuditEvent,
    OutboundMessage,
    PolicyEvaluation,
    RecoveryAction,
    RecoveryCase,
)
from backend.domain.enums import RecoveryActionState
from backend.llm.advisor import LLMAdvisor
from backend.policy.config_loader import PolicyConfig
from eval.dataset import configuration_hash
from eval.pipeline import new_run, run_scenario
from eval.statistics import bootstrap_difference, classification_metrics
from sim.scenarios import Scenario

EVAL_NOW = datetime(2026, 1, 1, 4, tzinfo=UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def run_arm(scenarios: list[Scenario], arm: str, seed: int, policy: PolicyConfig) -> list[dict[str, Any]]:
    session, gateway = new_run(policy)
    gateway.seed = seed
    advisor = LLMAdvisor.from_environment() if arm == "rules_llm" else None
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        result = run_scenario(scenario, arm, seed, policy, gateway, session, advisor)
        case = session.get(RecoveryCase, result.case_id)
        if case is None:
            raise RuntimeError(f"missing case {result.case_id}")
        actions = list(session.scalars(select(RecoveryAction).where(RecoveryAction.case_id == case.id)))
        executed = [action for action in actions if action.state in {RecoveryActionState.EXECUTED, RecoveryActionState.FAILED}]
        messages = list(session.scalars(select(OutboundMessage).where(OutboundMessage.case_id == case.id)))
        evaluations = list(session.scalars(select(PolicyEvaluation).where(PolicyEvaluation.case_id == case.id)))
        audits = list(session.scalars(select(AuditEvent).where(AuditEvent.case_id == case.id)))
        executed_action = executed[-1].action_type.value if executed else None
        executed_at = _aware(executed[-1].executed_at) if executed and executed[-1].executed_at else None
        elapsed_hours = ((executed_at - EVAL_NOW).total_seconds() / 3600) if executed_at else None
        attributed = bool(result.recovered and elapsed_hours is not None and elapsed_hours <= policy.values["attribution_window_hours"])
        false_rules = [
            rule["rule_id"]
            for evaluation in evaluations
            for rule in (evaluation.rules_fired if isinstance(evaluation.rules_fired, list) else [])
            if isinstance(rule, dict) and rule.get("passed") is False
        ]
        outside_window = sum(
            not (9 <= _aware(message.created_at).astimezone(ZoneInfo("Asia/Kolkata")).hour < 20)
            for message in messages
        )
        rows.append(
            {
                "key": scenario.key,
                "expected_category": ("CUSTOMER_ABANDONED" if scenario.case_class.value == "C_ABANDONED" else scenario.failure_category.value),
                "predicted_category": case.failure_category.value,
                "amount_paise": scenario.amount_paise,
                "case_class": scenario.case_class.value,
                "recovered": attributed,
                "state": case.state.value,
                "action": executed_action,
                "actions": sum(action.action_type.value != "WAIT" for action in executed),
                "contacts": len(messages),
                "charge_attempts": case.charge_attempts_used,
                "elapsed_hours": elapsed_hours,
                "policy_violations": int(result.policy_violation),
                "denied_rules": false_rules,
                "double_charge_incidents": sum(a.event_type == "DUPLICATE_CHARGE_COMPENSATION_REQUIRED" for a in audits),
                "messages_outside_window": outside_window,
            }
        )
    session.commit()
    if advisor is not None and rows:
        rows[0]["_llm_stats"] = advisor.stats.json()
    return rows


def _costs() -> dict[str, int]:
    values = yaml.safe_load(config_path("costs.yaml").read_text()) or {}
    return {str(key): int(value) for key, value in values.items()}


def _cost_config_hash() -> str:
    return hashlib.sha256(config_path("costs.yaml").read_bytes()).hexdigest()


def _recovery_by_category(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Summarize recovery outcomes by the expected failure category."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["expected_category"]), []).append(row)
    return {
        category: {
            "cases": len(category_rows),
            "recovered_cases": sum(bool(row["recovered"]) for row in category_rows),
            "recovery_rate": (
                sum(bool(row["recovered"]) for row in category_rows) / len(category_rows)
                if category_rows
                else 0.0
            ),
            "gross_recovered_paise": sum(
                int(row["amount_paise"]) for row in category_rows if row["recovered"]
            ),
        }
        for category, category_rows in sorted(grouped.items())
    }


def summarize(
    rows: list[dict[str, Any]], control_rows: list[dict[str, Any]], arm: str, seed: int, policy: PolicyConfig
) -> dict[str, Any]:
    count = len(rows)
    recovered = [bool(row["recovered"]) for row in rows]
    control_recovered = [bool(row["recovered"]) for row in control_rows]
    gross = sum(int(row["amount_paise"]) for row in rows if row["recovered"])
    control_gross = sum(int(row["amount_paise"]) for row in control_rows if row["recovered"])
    treatment_revenue = [int(row["amount_paise"]) if row["recovered"] else 0 for row in rows]
    control_revenue = [int(row["amount_paise"]) if row["recovered"] else 0 for row in control_rows]
    cost_map = _costs()
    total_cost = sum(cost_map.get(str(row["action"]), 0) for row in rows)
    denied: dict[str, int] = {}
    for row in rows:
        for rule in row["denied_rules"]:
            denied[str(rule)] = denied.get(str(rule), 0) + 1
    classification = classification_metrics(
        [{"expected": str(row["expected_category"]), "predicted": str(row["predicted_category"])} for row in rows]
    )
    stats = rows[0].get("_llm_stats", {}) if rows else {}
    requests = int(stats.get("requests", 0)) if isinstance(stats, dict) else 0
    schema_failures = int(stats.get("schema_failures", 0)) if isinstance(stats, dict) else 0
    fallbacks = int(stats.get("fallbacks", 0)) if isinstance(stats, dict) else 0
    cache_hits = int(stats.get("cache_hits", 0)) if isinstance(stats, dict) else 0
    rate = sum(recovered) / count if count else 0.0
    return {
        "arm": arm,
        "cases": count,
        "recovered_cases": sum(recovered),
        "recovery_rate": rate,
        "gross_recovered_paise": gross,
        "revenue_per_case_paise": gross / count if count else 0.0,
        "incremental_recovery_rate": rate - (sum(control_recovered) / count if count else 0.0),
        "incremental_revenue_paise": gross - control_gross,
        "bootstrap_95_ci": bootstrap_difference(recovered, control_recovered, seed),
        "bootstrap_revenue_95_ci": bootstrap_difference(treatment_revenue, control_revenue, seed + 1),
        "cost_total": total_cost,
        "cost_per_recovered_rupee": total_cost / (gross / 100) if gross else None,
        "behavior": {
            "actions_per_case": sum(int(row["actions"]) for row in rows) / count if count else 0.0,
            "contacts_per_recovered_case": sum(int(row["contacts"]) for row in rows if row["recovered"]) / sum(recovered) if sum(recovered) else 0.0,
            "wasted_actions": sum(bool(control_rows[i]["recovered"]) and int(row["actions"]) > 0 for i, row in enumerate(rows)),
            "stop_rate": sum(row["state"] == "STOPPED" for row in rows) / count if count else 0.0,
            "mean_time_to_recovery_hours": sum(float(row["elapsed_hours"] or 0) for row in rows if row["recovered"]) / sum(recovered) if sum(recovered) else None,
        },
        "recovery_by_category": _recovery_by_category(rows),
        "correctness": classification,
        "safety": {
            "policy_violations": sum(int(row["policy_violations"]) for row in rows),
            "denied_action_counts_by_rule": denied,
            "human_escalation_rate": sum(row["state"] == "AWAITING_APPROVAL" for row in rows) / count if count else 0.0,
            "double_charge_incidents": sum(int(row["double_charge_incidents"]) for row in rows),
            "messages_outside_window": sum(int(row["messages_outside_window"]) for row in rows),
        },
        "llm": {
            "mode": "deterministic-only",
            "available": False,
            "unavailable_reason": "LLM advisor is disabled by product decision",
            "schema_failure_rate": schema_failures / requests if requests else 0.0,
            "fallback_rate": fallbacks / max(1, requests + fallbacks),
            "mean_latency_ms": float(stats.get("mean_latency_ms", 0.0)) if isinstance(stats, dict) else 0.0,
            "cache_hit_rate": cache_hits / max(1, requests + cache_hits),
            "brier_score": None,
            "reliability_curve": [],
            "agreement_with_rules": None,
        },
        "metadata": {
            "seed": seed,
            "policy_config_hash": policy.config_hash,
            "scenario_config_hash": configuration_hash(),
            "cost_config_hash": _cost_config_hash(),
            "costs": cost_map,
            "attribution_window_hours": policy.values["attribution_window_hours"],
        },
    }


def evaluate(scenarios: list[Scenario], arms: list[str], seed: int, policy: PolicyConfig) -> list[dict[str, Any]]:
    control = run_arm(scenarios, "control", seed, policy)
    output = [summarize(control, control, "control", seed, policy)]
    rules_rows: list[dict[str, Any]] | None = None
    for arm in arms:
        if arm == "control":
            continue
        rows = run_arm(scenarios, arm, seed, policy)
        if arm == "rules":
            rules_rows = rows
        item = summarize(rows, control, arm, seed, policy)
        if arm == "rules_llm" and rules_rows:
            agreements = sum(
                left.get("action") == right.get("action")
                for left, right in zip(rows, rules_rows, strict=True)
            )
            item["llm"]["agreement_with_rules"] = agreements / len(rows) if rows else 1.0
        output.append(item)
    return output


__all__ = ["evaluate", "run_arm", "summarize"]
