from backend.domain.enums import FailureCategory
from backend.domain.failure_taxonomy import map_error


def test_unknown_errors_are_never_guessed() -> None:
    assert map_error("unverified_code") is FailureCategory.UNKNOWN
