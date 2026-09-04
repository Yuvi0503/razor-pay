import hashlib
from pathlib import Path

from sim.scenarios import Scenario


def configuration_hash() -> str:
    """Hash the scenario configuration, not generated results."""
    return hashlib.sha256(Path("config/sim/scenarios.yaml").read_bytes()).hexdigest()


def split(scenarios: list[Scenario], name: str) -> list[Scenario]:
    if name == "all":
        return list(scenarios)
    buckets = {"train": range(60), "dev": range(60, 80), "test": range(80, 100)}
    wanted = buckets[name]
    return [
        s for s in scenarios if int(hashlib.sha256(s.key.encode()).hexdigest(), 16) % 100 in wanted
    ]


__all__ = ["configuration_hash", "split"]
