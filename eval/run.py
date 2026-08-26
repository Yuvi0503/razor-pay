import argparse

from backend.policy.config_loader import load
from eval.arms import choose
from eval.dataset import split
from eval.metrics import ArmMetrics
from eval.report import write
from sim.gateway import SimulatedGateway
from sim.scenarios import generate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="all")
    parser.add_argument("--split", default="test", choices=["train", "dev", "test"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    arms = (
        ["control", "naive", "rules", "rules_llm", "oracle"]
        if args.arms == "all"
        else args.arms.split(",")
    )
    scenarios, cfg, gateway = (
        split(generate(args.count, args.seed), args.split),
        load(),
        SimulatedGateway(args.seed),
    )
    output = []
    for arm in arms:
        recovered = [
            (
                s,
                gateway.execute(
                    s, choose("rules" if arm == "rules_llm" else arm, s, cfg, args.seed)
                ),
            )
            for s in scenarios
        ]
        count = sum(ok for _, ok in recovered)
        output.append(
            ArmMetrics(
                arm,
                len(scenarios),
                count,
                sum(s.amount_paise for s, ok in recovered if ok),
                count / len(scenarios) if scenarios else 0,
            ).json()
        )
    report = write(output, args.seed)
    print(report)
    for row in output:
        print(f"{row['arm']:10} {row['recovery_rate']:.1%} {row['gross_recovered_paise']} paise")


if __name__ == "__main__":
    main()
