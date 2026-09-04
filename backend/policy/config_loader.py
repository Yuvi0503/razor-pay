import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    values: dict[str, Any]
    config_hash: str


def load(path: str = "config/policy.yaml") -> PolicyConfig:
    raw = Path(path).read_bytes()
    return PolicyConfig(yaml.safe_load(raw) or {}, hashlib.sha256(raw).hexdigest())
