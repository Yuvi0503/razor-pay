from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.db.base import Base
from backend.db.engine import get_session
from backend.db.models import HumanApproval, RecoveryAction
from backend.db.repositories.recovery import RecoveryRepository
from backend.domain.enums import (
    ActionType,
    ApprovalDecision,
    AuditActor,
    CaseClass,
    CaseState,
    DecisionSource,
    FailureCategory,
    Recoverability,
    VerdictType,
)
from backend.policy.config_loader import load


def test_dashboard_reads_cases_timeline_policy_and_approval_actions(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = RecoveryRepository(session)
        merchant = repository.merchant("merchant-dashboard")
        customer = repository.customer(merchant.id, "customer-dashboard")
        order = repository.order(merchant.id, customer.id, "order-dashboard", 99900)
        case = repository.open_case(
            merchant_id=merchant.id,
            customer_id=customer.id,
            order_id=order.id,
            subscription_id=None,
            case_class=CaseClass.B_ONEOFF,
            amount_paise=99900,
            failure_category=FailureCategory.INSUFFICIENT_FUNDS,
            recoverability=Recoverability.ASSISTED,
        )
        decision = repository.decision(
            case.id,
            ActionType.CREATE_PAYMENT_LINK,
            0,
            DecisionSource.RULE,
            ["ELIGIBLE_CREATE_PAYMENT_LINK"],
            {"case_class": "B_ONEOFF"},
        )
        repository.policy_evaluation(
            decision.id,
            case.id,
            VerdictType.ALLOW,
            ActionType.CREATE_PAYMENT_LINK,
            [{"rule_id": "P01", "passed": True}],
            load().config_hash,
        )
        repository.audit("CASE_OPENED", AuditActor.SYSTEM, case.id, {"source": "test"})
        approval = HumanApproval(case_id=case.id, decision_id=decision.id)
        case.state = CaseState.AWAITING_APPROVAL
        session.add(approval)
        session.commit()

        def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        monkeypatch.setenv("APPROVAL_API_TOKEN", "dashboard-test-token")
        client = TestClient(app)
        try:
            listed = client.get("/api/cases")
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == case.id

            detail = client.get(f"/api/cases/{case.id}")
            assert detail.status_code == 200
            assert {item["kind"] for item in detail.json()["timeline"]} >= {"audit", "decision", "policy"}

            policy = client.get("/api/policy")
            assert policy.status_code == 200
            assert len(policy.json()["config_hash"]) == 64

            pending = client.get("/api/approvals")
            assert pending.status_code == 200
            assert pending.json()[0]["id"] == approval.id

            denied = client.post(
                f"/api/approvals/{approval.id}",
                json={"decision": ApprovalDecision.APPROVED.value, "note": "reviewed"},
            )
            assert denied.status_code == 403

            approved = client.post(
                f"/api/approvals/{approval.id}",
                headers={"X-Approval-Token": "dashboard-test-token"},
                json={"decision": ApprovalDecision.APPROVED.value, "note": "reviewed"},
            )
            assert approved.status_code == 200
            assert approved.json()["case_state"] == CaseState.SCHEDULED.value
            action_id = approved.json()["action_id"]
            assert action_id is not None
            action = session.get(RecoveryAction, action_id)
            assert action is not None
            assert action.action_type is ActionType.CREATE_PAYMENT_LINK
        finally:
            app.dependency_overrides.pop(get_session, None)
