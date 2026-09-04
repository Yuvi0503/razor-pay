from pathlib import Path

import yaml

from backend.domain.enums import FailureCategory
from backend.domain.failure_taxonomy import map_error


def test_unknown_errors_are_never_guessed() -> None:
    assert map_error("unverified_code") is FailureCategory.UNKNOWN


def test_every_configured_taxonomy_entry_maps_to_a_valid_category() -> None:
    mapping = yaml.safe_load(Path("config/taxonomy.yaml").read_text()) or {}
    assert isinstance(mapping, dict)
    for raw_code, category in mapping.items():
        assert isinstance(raw_code, str)
        assert FailureCategory(category) is not FailureCategory.UNKNOWN


def test_unmapped_and_empty_error_codes_fall_back_to_unknown(tmp_path) -> None:
    taxonomy = tmp_path / "taxonomy.yaml"
    taxonomy.write_text("verified_code: INSUFFICIENT_FUNDS\n")
    assert map_error("verified_code", str(taxonomy)) is FailureCategory.INSUFFICIENT_FUNDS
    assert map_error("not_verified", str(taxonomy)) is FailureCategory.UNKNOWN
    assert map_error(None, str(taxonomy)) is FailureCategory.UNKNOWN
