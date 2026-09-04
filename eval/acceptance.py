"""Acceptance gates for the simulator and deterministic evaluation pipeline."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import TypedDict

from backend.policy.config_loader import load
from eval.pipeline import new_run, run_scenario
from sim.scenarios import canonical, generate


class ScenarioDistribution(TypedDict):
    cases: int
    classes: dict[str, int]
    failure_categories: dict[str, int]
    methods: dict[str, int]
    issuers_or_banks: dict[str, int]
    amounts_paise: dict[str, int]
    organic_payers: dict[str, int]


def scenario_distribution(count: int = 1000, seed: int = 42) -> ScenarioDistribution:
    """Return stable, JSON-friendly distribution counts for a generated dataset."""
    scenarios = generate(count, seed)
    return {
        "cases": len(scenarios),
        "classes": dict(sorted(Counter(item.case_class.value for item in scenarios).items())),
        "failure_categories": dict(
            sorted(Counter(item.failure_category.value for item in scenarios).items())
        ),
        "methods": dict(sorted(Counter(item.method for item in scenarios).items())),
        "issuers_or_banks": dict(
            sorted(Counter(item.issuer_or_bank for item in scenarios).items())
        ),
        "amounts_paise": dict(
            sorted((str(amount), total) for amount, total in Counter(item.amount_paise for item in scenarios).items())
        ),
        "organic_payers": dict(
            sorted(Counter(str(item.organic_payer).lower() for item in scenarios).items())
        ),
    }


def deterministic_generator_acceptance(
    count: int = 1000, seed: int = 42, report_path: Path | None = None
) -> ScenarioDistribution:
    """Verify byte-identical generation and expected fixed-seed distributions."""
    first = json.dumps(
        canonical(generate(count, seed)), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    second = json.dumps(
        canonical(generate(count, seed)), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if first != second:
        raise AssertionError("scenario generator output is not byte-identical for the same seed")

    distribution = scenario_distribution(count, seed)
    if count == 1000 and seed == 42:
        expected = {
            "classes": {"A_MANDATE": 268, "B_ONEOFF": 532, "C_ABANDONED": 200},
            "failure_categories": {
                "AUTHENTICATION_FAILED": 250,
                "INSUFFICIENT_FUNDS": 250,
                "TEMPORARY_BANK_ERROR": 250,
                "UNKNOWN": 250,
            },
            "methods": {"card": 250, "upi": 750},
            "issuers_or_banks": {"sim-bank-0": 334, "sim-bank-1": 333, "sim-bank-2": 333},
            "amounts_paise": {"1250000": 245, "249900": 252, "750000": 247, "99900": 256},
            "organic_payers": {"false": 909, "true": 91},
        }
        for field, expected_counts in expected.items():
            if distribution[field] != expected_counts:  # type: ignore[literal-required]
                raise AssertionError(
                    f"unexpected {field} distribution: {distribution[field]} != {expected_counts}"
                )

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(distribution, indent=2, sort_keys=True) + "\n")
    return distribution


def run(count: int = 500, seed: int = 42) -> dict[str, object]:
    cfg = load()
    summary: dict[str, object] = {"count": count, "seed": seed, "arms": {}}
    for arm in ("naive", "rules"):
        session, gateway = new_run(cfg)
        gateway.seed = seed
        results = [run_scenario(s, arm, seed, cfg, gateway, session) for s in generate(count, seed)]
        session.commit()
        terminal = {"RECOVERED", "EXHAUSTED", "STOPPED", "EXPIRED"}
        states = {item.state.value for item in results}
        violations = sum(item.policy_violation for item in results)
        arm_result = {
            "cases": len(results),
            "terminal_cases": sum(item.state.value in terminal for item in results),
            "states": sorted(states),
            "policy_violations": violations,
        }
        if arm_result["terminal_cases"] != count or violations:
            raise AssertionError(f"{arm} acceptance failed: {arm_result}")
        summary["arms"][arm] = arm_result  # type: ignore[index]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(run(args.count, args.seed), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
