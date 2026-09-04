import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.charts import bar_chart, line_chart


def write(
    metrics: list[dict[str, Any]],
    seed: int,
    metadata: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> Path:
    target = output_dir or Path("eval/reports") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target.mkdir(parents=True, exist_ok=True)
    control = next(item for item in metrics if item["arm"] == "control")
    control_rate = float(control["recovery_rate"])
    for item in metrics:
        item["incremental_recovery_rate"] = round(float(item["recovery_rate"]) - control_rate, 4)
    payload = {
        "seed": seed,
        "metadata": metadata or {},
        "metrics": metrics,
        "notes": [
            "Simulator outcome model; not production outcomes.",
            "Policy violations must remain zero.",
            "Metrics are generated from persisted orchestration records.",
        ],
    }
    (target / "metrics.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    rules = next((item for item in metrics if item["arm"] == "rules"), None)
    category_rates = [
        float(value["recovery_rate"])
        for value in (rules or {}).get("recovery_by_category", {}).values()
    ]
    cumulative = [
        sum(float(item["gross_recovered_paise"]) for item in metrics[:index + 1])
        for index in range(len(metrics))
    ]
    # No calibrated confidence is produced in deterministic-only mode. Keep the required
    # artifact, but do not mislabel arm recovery rates as a reliability curve.
    bar_chart(target / "reliability_curve.png", [])
    bar_chart(target / "recovery_by_category.png", category_rates, color=(220, 120, 45))
    line_chart(target / "cumulative_revenue.png", [cumulative])
    lines = [
        "# Revenue recovery evaluation",
        "",
        f"Seed: `{seed}`",
        f"Split: `{(metadata or {}).get('split', 'unknown')}`",
        "",
        "| Arm | Cases | Recovered | Rate | Gross paise | Incremental pp | Bootstrap 95% CI |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in metrics:
        interval = item["bootstrap_95_ci"]
        lines.append(
            f"| {item['arm']} | {item['cases']} | {item['recovered_cases']} | "
            f"{float(item['recovery_rate']):.1%} | {item['gross_recovered_paise']} | "
            f"{float(item['incremental_recovery_rate']) * 100:+.1f} | "
            f"[{float(interval['lower']):+.3f}, {float(interval['upper']):+.3f}] |"
        )
    lines += [
        "",
        "## Metric coverage",
        "",
        (
            "The JSON report contains money, behaviour, recovery-by-category, correctness, safety, "
            "and deterministic-only LLM status metrics."
        ),
        "",
        (
            "LLM calibration metrics are unavailable because the active product mode is "
            "deterministic-only; no confidence values are fabricated."
        ),
        "",
        "### Recovery by category (rules arm)",
        "",
        "| Category | Cases | Recovered | Rate | Gross paise |",
        "|---|---:|---:|---:|---:|",
    ]
    for category, value in (rules or {}).get("recovery_by_category", {}).items():
        lines.append(
            f"| {category} | {value['cases']} | {value['recovered_cases']} | "
            f"{float(value['recovery_rate']):.1%} | {value['gross_recovered_paise']} |"
        )
    lines += [
        "",
        "Charts: `reliability_curve.png`, `recovery_by_category.png`, `cumulative_revenue.png`.",
        "",
        "These are simulator results, not production recovery claims.",
    ]
    (target / "report.md").write_text("\n".join(lines) + "\n")
    return target


__all__ = ["write"]
