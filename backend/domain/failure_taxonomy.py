from pathlib import Path

import yaml

from backend.configuration import config_path

from .enums import FailureCategory


def map_error(raw_code: str | None, path: str | None = None) -> FailureCategory:
    mapping = yaml.safe_load((config_path("taxonomy.yaml") if path is None else Path(path)).read_text()) or {}
    value = mapping.get(raw_code or "")
    return FailureCategory(value) if value else FailureCategory.UNKNOWN
