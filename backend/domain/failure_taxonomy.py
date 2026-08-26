from pathlib import Path

import yaml

from .enums import FailureCategory


def map_error(raw_code: str | None, path: str = "config/taxonomy.yaml") -> FailureCategory:
    mapping = yaml.safe_load(Path(path).read_text()) or {}
    value = mapping.get(raw_code or "")
    return FailureCategory(value) if value else FailureCategory.UNKNOWN
