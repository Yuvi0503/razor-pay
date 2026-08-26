from .enums import CaseState

TERMINAL = {CaseState.RECOVERED, CaseState.EXHAUSTED, CaseState.STOPPED, CaseState.EXPIRED}
TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.OPEN: {CaseState.CLASSIFIED, CaseState.STOPPED, CaseState.EXPIRED},
    CaseState.CLASSIFIED: {CaseState.DECIDED, CaseState.STOPPED, CaseState.EXHAUSTED},
    CaseState.DECIDED: {
        CaseState.AWAITING_APPROVAL,
        CaseState.SCHEDULED,
        CaseState.STOPPED,
        CaseState.EXHAUSTED,
    },
    CaseState.AWAITING_APPROVAL: {CaseState.DECIDED, CaseState.SCHEDULED, CaseState.STOPPED},
    CaseState.SCHEDULED: {CaseState.EXECUTING, CaseState.DECIDED, CaseState.EXPIRED},
    CaseState.EXECUTING: {CaseState.VERIFYING, CaseState.DECIDED},
    CaseState.VERIFYING: {
        CaseState.RECOVERED,
        CaseState.DECIDED,
        CaseState.EXHAUSTED,
        CaseState.EXPIRED,
    },
    **{state: set() for state in TERMINAL},
}


class IllegalTransition(ValueError):
    pass


def transition(current: CaseState, target: CaseState) -> CaseState:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current} -> {target} is not legal")
    return target
