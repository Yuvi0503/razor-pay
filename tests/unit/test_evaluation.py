import json

from backend.policy.config_loader import load
from eval.acceptance import deterministic_generator_acceptance
from eval.dataset import configuration_hash, split
from eval.harness import evaluate
from eval.report import write
from eval.statistics import bootstrap_difference
from sim.scenarios import canonical, generate


def test_scenario_generation_and_split_are_deterministic() -> None:
    first = json.dumps(canonical(generate(1000, 42)), sort_keys=True, separators=(",", ":"))
    second = json.dumps(canonical(generate(1000, 42)), sort_keys=True, separators=(",", ":"))
    assert first == second
    scenarios = generate(1000, 42)
    assert len(split(scenarios, "train")) + len(split(scenarios, "dev")) + len(split(scenarios, "test")) == 1000
    assert len(configuration_hash()) == 64


def test_1000_case_generator_acceptance_and_distribution_report(tmp_path) -> None:
    report = tmp_path / "scenario-distribution.json"
    distribution = deterministic_generator_acceptance(report_path=report)

    assert distribution["cases"] == 1000
    assert distribution["classes"] == {"A_MANDATE": 268, "B_ONEOFF": 532, "C_ABANDONED": 200}
    assert report.exists()
    assert json.loads(report.read_text()) == distribution


def test_bootstrap_is_seeded_and_reports_requested_resamples() -> None:
    result = bootstrap_difference([1, 0, 1, 1], [0, 0, 1, 0], seed=42, resamples=1000)
    assert result == bootstrap_difference([1, 0, 1, 1], [0, 0, 1, 0], seed=42, resamples=1000)
    assert result["resamples"] == 1000
    assert result["estimate"] == 0.5


def test_harness_reports_all_metric_groups_and_png_artifacts(tmp_path) -> None:
    scenarios = split(generate(100, 42), "test")
    metrics = evaluate(scenarios, ["naive", "rules", "rules_llm", "oracle"], 42, load())
    second_metrics = evaluate(scenarios, ["naive", "rules", "rules_llm", "oracle"], 42, load())
    target = write(metrics, 42, {"split": "test", "sample_size": len(scenarios)}, tmp_path / "report")
    second_target = write(second_metrics, 42, {"split": "test", "sample_size": len(scenarios)}, tmp_path / "report-second")
    assert {item["arm"] for item in metrics} == {"control", "naive", "rules", "rules_llm", "oracle"}
    for item in metrics:
        assert {"behavior", "correctness", "safety", "llm", "bootstrap_95_ci"} <= set(item)
        assert item["safety"]["policy_violations"] == 0
        assert item["recovery_by_category"]
        assert item["llm"]["mode"] == "deterministic-only"
        assert item["llm"]["available"] is False
    assert (target / "metrics.json").read_text()
    assert (target / "metrics.json").read_bytes() == (second_target / "metrics.json").read_bytes()
    for name in ("reliability_curve.png", "recovery_by_category.png", "cumulative_revenue.png"):
        assert (target / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
