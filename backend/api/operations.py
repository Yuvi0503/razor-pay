"""Read models and restricted approval operations for the demo dashboard."""

import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.engine import get_session
from backend.db.models import (
    AuditEvent,
    HumanApproval,
    OutboundMessage,
    PaymentAttempt,
    PolicyEvaluation,
    RecoveryAction,
    RecoveryCase,
    RecoveryDecision,
)
from backend.domain.enums import ApprovalDecision, AuditActor, CaseState, RecoveryResolution
from backend.domain.state_machine import transition
from backend.policy.config_loader import load

router = APIRouter(prefix="/api")


def _date(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _value(value: object) -> object:
    return value.value if hasattr(value, "value") else value


def _case_summary(session: Session, case: RecoveryCase) -> dict[str, object]:
    decision = session.scalar(
        select(RecoveryDecision)
        .where(RecoveryDecision.case_id == case.id)
        .order_by(RecoveryDecision.created_at.desc())
    )
    action = session.scalar(
        select(RecoveryAction)
        .where(RecoveryAction.case_id == case.id)
        .order_by(RecoveryAction.created_at.desc())
    )
    return {
        "id": case.id,
        "customer_id": case.customer_id,
        "order_id": case.order_id,
        "subscription_id": case.subscription_id,
        "case_class": _value(case.case_class),
        "failure_category": _value(case.failure_category),
        "recoverability": _value(case.recoverability),
        "state": _value(case.state),
        "amount_at_risk_paise": case.amount_at_risk_paise,
        "contacts_used": case.contacts_used,
        "charge_attempts_used": case.charge_attempts_used,
        "opened_at": _date(case.opened_at),
        "resolved_at": _date(case.resolved_at),
        "resolution": _value(case.resolution),
        "recovered_amount_paise": case.recovered_amount_paise,
        "latest_decision": {
            "action": _value(decision.proposed_action),
            "source": _value(decision.source),
            "delay_minutes": decision.proposed_delay_minutes,
            "reason_codes": decision.reason_codes,
            "created_at": _date(decision.created_at),
        } if decision else None,
        "latest_action": {
            "id": action.id,
            "action": _value(action.action_type),
            "state": _value(action.state),
            "scheduled_for": _date(action.scheduled_for),
            "executed_at": _date(action.executed_at),
            "skip_reason": action.skip_reason,
            "result": action.result,
        } if action else None,
    }


@router.get("/cases")
def cases(
    state: str | None = Query(default=None),
    case_class: str | None = Query(default=None),
    failure_category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    statement = select(RecoveryCase).order_by(RecoveryCase.opened_at.desc()).limit(limit)
    if state:
        statement = statement.where(RecoveryCase.state == state)
    if case_class:
        statement = statement.where(RecoveryCase.case_class == case_class)
    if failure_category:
        statement = statement.where(RecoveryCase.failure_category == failure_category)
    return [_case_summary(session, case) for case in session.scalars(statement)]


@router.get("/cases/{case_id}")
def case_detail(case_id: str, session: Session = Depends(get_session)) -> dict[str, object]:  # noqa: B008
    case = session.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    timeline: list[dict[str, object]] = []
    for item in session.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id)):
        timeline.append({"at": _date(item.occurred_at), "kind": "audit", "title": item.event_type, "actor": _value(item.actor), "payload": item.payload})
    for item in session.scalars(select(RecoveryDecision).where(RecoveryDecision.case_id == case_id)):
        timeline.append({"at": _date(item.created_at), "kind": "decision", "title": f"Proposed {_value(item.proposed_action)}", "actor": _value(item.source), "payload": {"delay_minutes": item.proposed_delay_minutes, "reason_codes": item.reason_codes, "llm_fallback_reason": item.llm_fallback_reason}})
    for item in session.scalars(select(PolicyEvaluation).where(PolicyEvaluation.case_id == case_id)):
        timeline.append({"at": _date(item.evaluated_at), "kind": "policy", "title": f"Policy {_value(item.verdict)}", "actor": "RULE", "payload": {"final_action": _value(item.final_action), "policy_config_hash": item.policy_config_hash, "rules_fired": item.rules_fired}})
    for item in session.scalars(select(RecoveryAction).where(RecoveryAction.case_id == case_id)):
        timeline.append({"at": _date(item.created_at), "kind": "action", "title": f"Action {_value(item.action_type)}", "actor": "SYSTEM", "payload": {"state": _value(item.state), "scheduled_for": _date(item.scheduled_for), "result": item.result, "skip_reason": item.skip_reason}})
    for item in session.scalars(select(PaymentAttempt).where((PaymentAttempt.order_id == case.order_id) if case.order_id else (PaymentAttempt.subscription_id == case.subscription_id))):
        timeline.append({"at": _date(item.occurred_at), "kind": "payment", "title": f"Payment {_value(item.status)}", "actor": _value(item.initiated_by), "payload": {"provider_payment_id": item.provider_payment_id, "amount_paise": item.amount_paise, "failure_category": _value(item.failure_category)}})
    for item in session.scalars(select(OutboundMessage).where(OutboundMessage.case_id == case_id)):
        timeline.append({"at": _date(item.created_at), "kind": "message", "title": f"Rendered {item.template_id}", "actor": _value(item.generated_by), "payload": {"channel": _value(item.channel), "subject": item.rendered_subject, "body": item.rendered_body, "delivery": "not sent"}})
    timeline.sort(key=lambda item: item["at"] or "")
    return {"case": _case_summary(session, case), "timeline": timeline}


class ApprovalUpdate(BaseModel):
    decision: ApprovalDecision
    note: str = Field(default="", max_length=1000)


def _require_approval_token(token: str | None) -> None:
    expected = os.getenv("APPROVAL_API_TOKEN", "").strip()
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(403, "restricted approval API is not configured or token is invalid")


@router.get("/approvals")
def approvals(
    pending_only: bool = True,
    session: Session = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    statement = select(HumanApproval).order_by(HumanApproval.requested_at.desc())
    if pending_only:
        statement = statement.where(HumanApproval.decision.is_(None))
    output = []
    for approval in session.scalars(statement):
        case = session.get(RecoveryCase, approval.case_id)
        if case:
            output.append({"id": approval.id, "requested_at": _date(approval.requested_at), "decided_at": _date(approval.decided_at), "decision": _value(approval.decision), "note": approval.note, "case": _case_summary(session, case)})
    return output


@router.post("/approvals/{approval_id}")
def update_approval(
    approval_id: str,
    update: ApprovalUpdate,
    x_approval_token: str | None = Header(default=None),
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    _require_approval_token(x_approval_token)
    approval = session.get(HumanApproval, approval_id)
    if approval is None:
        raise HTTPException(404, "approval not found")
    if approval.decision is not None:
        raise HTTPException(409, "approval already decided")
    case = session.get(RecoveryCase, approval.case_id)
    if case is None or case.state is not CaseState.AWAITING_APPROVAL:
        raise HTTPException(409, "case is no longer awaiting approval")
    approval.decision = update.decision
    approval.note = update.note
    approval.decided_at = datetime.now(UTC)
    if update.decision is ApprovalDecision.REJECTED:
        transition(case.state, CaseState.STOPPED)
        case.state = CaseState.STOPPED
        case.resolution = RecoveryResolution.STOPPED
        case.resolved_at = datetime.now(UTC)
    else:
        transition(case.state, CaseState.DECIDED)
        case.state = CaseState.DECIDED
    session.add(AuditEvent(case_id=case.id, event_type=f"APPROVAL_{update.decision.value}", actor=AuditActor.HUMAN, payload={"note": update.note}))
    session.commit()
    return {"approval_id": approval.id, "decision": update.decision.value, "case_id": case.id, "case_state": case.state.value}


@router.get("/policy")
def policy() -> dict[str, object]:
    configured = load()
    return {"config_hash": configured.config_hash, "values": configured.values}


@router.get("/evaluation")
def evaluation() -> dict[str, object]:
    configured_path = os.getenv("EVAL_REPORT_PATH", "").strip()
    if configured_path:
        report = Path(configured_path)
    else:
        reports = sorted(Path("eval/reports").glob("*/metrics.json"))
        report = reports[-1] if reports else None
    if report is None or not report.exists():
        return {"available": False, "message": "Run python -m eval.run --arms all --split test --seed 42 to generate a report."}
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "stored evaluation report is invalid") from exc
    return {"available": True, "path": str(report), "report": payload}


__all__ = ["router"]
