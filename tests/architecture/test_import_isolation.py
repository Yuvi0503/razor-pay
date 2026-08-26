from pathlib import Path


def test_backend_never_imports_hidden_outcome_model() -> None:
    offenders = [
        path for path in Path("backend").rglob("*.py") if "sim.outcome_model" in path.read_text()
    ]
    assert offenders == []
