import hashlib

from sim.scenarios import Scenario


def split(scenarios: list[Scenario], name: str) -> list[Scenario]:
    buckets = {"train": range(60), "dev": range(60, 80), "test": range(80, 100)}
    wanted = buckets[name]
    return [
        s for s in scenarios if int(hashlib.sha256(s.key.encode()).hexdigest(), 16) % 100 in wanted
    ]
