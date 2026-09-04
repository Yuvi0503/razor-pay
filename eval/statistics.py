"""Deterministic statistics used by the evaluation harness."""

from collections.abc import Sequence
from random import Random


def bootstrap_difference(
    treatment: Sequence[float],
    control: Sequence[float],
    seed: int,
    resamples: int = 1000,
) -> dict[str, float | int]:
    if len(treatment) != len(control):
        raise ValueError("paired bootstrap requires equal treatment and control lengths")
    if not treatment:
        return {"estimate": 0.0, "lower": 0.0, "upper": 0.0, "resamples": resamples}
    estimate = sum(treatment) / len(treatment) - sum(control) / len(control)
    rng = Random(seed)
    values: list[float] = []
    for _ in range(resamples):
        indices = [rng.randrange(len(treatment)) for _ in treatment]
        values.append(
            sum(treatment[index] - control[index] for index in indices) / len(indices)
        )
    values.sort()
    return {
        "estimate": estimate,
        "lower": values[int(0.025 * (len(values) - 1))],
        "upper": values[int(0.975 * (len(values) - 1))],
        "resamples": resamples,
    }


def classification_metrics(rows: list[dict[str, str]]) -> dict[str, object]:
    categories = sorted({row["expected"] for row in rows} | {row["predicted"] for row in rows})
    matrix = {expected: {predicted: 0 for predicted in categories} for expected in categories}
    for row in rows:
        matrix[row["expected"]][row["predicted"]] += 1
    scores: dict[str, dict[str, float]] = {}
    for category in categories:
        true_positive = matrix[category][category]
        predicted = sum(matrix[expected][category] for expected in categories)
        actual = sum(matrix[category].values())
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / actual if actual else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores[category] = {"precision": precision, "recall": recall, "f1": f1}
    macro_f1 = sum(score["f1"] for score in scores.values()) / len(scores) if scores else 0.0
    unknown_rate = sum(row["predicted"] == "UNKNOWN" for row in rows) / len(rows) if rows else 0.0
    return {"per_category": scores, "confusion_matrix": matrix, "macro_f1": macro_f1, "unknown_rate": unknown_rate}


__all__ = ["bootstrap_difference", "classification_metrics"]
