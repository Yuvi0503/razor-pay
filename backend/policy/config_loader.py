import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from backend.configuration import config_path


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    values: dict[str, Any]
    config_hash: str


def load(path: str | None = None) -> PolicyConfig:
    raw = (config_path("policy.yaml") if path is None else Path(path)).read_bytes()
    return PolicyConfig(yaml.safe_load(raw) or {}, hashlib.sha256(raw).hexdigest())
