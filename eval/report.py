import json
from datetime import UTC, datetime
from pathlib import Path


def write(metrics: list[dict], seed: int) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = Path("eval/reports") / timestamp
    target.mkdir(parents=True, exist_ok=True)
    control = next(item for item in metrics if item["arm"] == "control")
    for item in metrics:
        item["incremental_recovery_rate"] = round(
            item["recovery_rate"] - control["recovery_rate"], 4
        )
    payload = {
        "seed": seed,
        "metrics": metrics,
        "notes": [
            "Simulator outcome model; not production outcomes.",
            "Policy violations must remain zero.",
        ],
    }
    (target / "metrics.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    lines = [
        "# Revenue recovery evaluation",
        "",
        f"Seed: `{seed}`",
        "",
        "| Arm | Cases | Recovered | Recovery rate | Gross paise | Incremental pp |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {m['arm']} | {m['cases']} | {m['recovered_cases']} | {m['recovery_rate']:.1%} | {m['gross_recovered_paise']} | {m['incremental_recovery_rate'] * 100:+.1f} |"
        for m in metrics
    ]
    (target / "report.md").write_text("\n".join(lines) + "\n")
    return target
