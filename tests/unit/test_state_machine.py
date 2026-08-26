import pytest

from backend.domain.enums import CaseState
from backend.domain.state_machine import IllegalTransition, transition


def test_legal_transition() -> None:
    assert transition(CaseState.OPEN, CaseState.CLASSIFIED) is CaseState.CLASSIFIED


def test_terminal_state_cannot_leave() -> None:
    with pytest.raises(IllegalTransition):
        transition(CaseState.RECOVERED, CaseState.DECIDED)
