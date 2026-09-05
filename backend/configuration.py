"""Resolve repository configuration in development and packaged deployments."""

import os
from pathlib import Path


def config_path(relative: str) -> Path:
    """Return an override, source-tree, or bundled configuration file."""
    override = os.getenv("REVENUE_RECOVERY_CONFIG_DIR", "").strip()
    candidates = []
    if override:
        candidates.append(Path(override) / relative)
    candidates.append(Path(__file__).resolve().parent.parent / "config" / relative)
    candidates.append(Path(__file__).resolve().parent / "resources" / "config" / relative)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"missing revenue-recovery configuration: {relative}")


__all__ = ["config_path"]
