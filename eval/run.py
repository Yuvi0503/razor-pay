import argparse

from backend.policy.config_loader import load
from eval.dataset import split
from eval.harness import evaluate
from eval.report import write
from sim.scenarios import generate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="all")
    parser.add_argument("--split", default="test", choices=["train", "dev", "test", "all"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    arms = (
        ["control", "naive", "rules", "rules_llm", "oracle"]
        if args.arms == "all"
        else args.arms.split(",")
    )
    scenarios, cfg = split(generate(args.count, args.seed), args.split), load()
    output = evaluate(scenarios, arms, args.seed, cfg)
    report = write(output, args.seed, {"split": args.split, "sample_size": len(scenarios)})
    print(report)
    for row in output:
        print(f"{row['arm']:10} {float(row['recovery_rate']):.1%} {row['gross_recovered_paise']} paise")


if __name__ == "__main__":
    main()
