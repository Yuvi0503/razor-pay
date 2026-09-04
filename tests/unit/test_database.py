import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db.base import Base
from backend.db.models import AuditEvent, PaymentAttempt, PolicyEvaluation, RawEvent, RecoveryCase
from backend.db.repositories import RawEventRepository
from backend.ingestion.processor import process_pending
from backend.policy.config_loader import load
from sim.gateway import SimulatedGateway


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_metadata_contains_all_persistence_tables(db_engine) -> None:
    expected = {
        "merchants",
        "customers",
        "customer_consent",
        "orders",
        "subscriptions",
        "payment_attempts",
        "recovery_cases",
        "recovery_decisions",
        "policy_evaluations",
        "recovery_actions",
        "human_approvals",
        "outbound_messages",
        "audit_events",
        "raw_events",
    }
    assert set(Base.metadata.tables) == expected
    assert "policy_config_hash" in PolicyEvaluation.__table__.c


def test_raw_events_deduplicate_by_provider_event_id(db_engine) -> None:
    with Session(db_engine) as session:
        repository = RawEventRepository(session)
        assert repository.insert_if_new(
            provider_event_id="evt_123",
            event_type="payment.failed",
            payload={"event": "payment.failed"},
        )
        session.commit()

        assert not repository.insert_if_new(
            provider_event_id="evt_123",
            event_type="payment.failed",
            payload={"event": "payment.failed", "duplicate": True},
        )
        session.commit()

        count = session.scalar(select(func.count()).select_from(RawEvent))
        assert count == 1


def test_webhook_persists_valid_event_and_returns_duplicate(db_engine, monkeypatch) -> None:
    from backend.api.main import app
    from backend.db.engine import get_session

    secret = "test-webhook-secret"
    raw = b'{"event":"payment.failed"}'
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    def override_session():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", secret)
    client = TestClient(app)
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_integration_123",
    }
    try:
        accepted = client.post("/webhooks/razorpay", content=raw, headers=headers)
        duplicate = client.post("/webhooks/razorpay", content=raw, headers=headers)
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert accepted.status_code == 200
    assert accepted.json() == {"status": "accepted"}
    assert duplicate.status_code == 200
    assert duplicate.json() == {"status": "duplicate"}


def test_duplicate_webhook_creates_one_case_after_worker_processing(db_engine, monkeypatch) -> None:
    from backend.api.main import app
    from backend.db.engine import get_session

    secret = "test-webhook-secret"
    payload = {
        "event": "payment.failed",
        "merchant_id": "merchant-duplicate",
        "customer_id": "customer-duplicate",
        "payload": {
            "payment": {
                "entity": {
                    "id": "payment-duplicate",
                    "amount": 99900,
                    "order_id": "order-duplicate",
                    "method": "upi",
                    "error": {"code": "insufficient_funds"},
                }
            },
            "order": {
                "entity": {
                    "id": "order-duplicate",
                    "amount": 99900,
                    "currency": "INR",
                    "status": "attempted",
                    "customer_id": "customer-duplicate",
                }
            },
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    def override_session():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", secret)
    client = TestClient(app)
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_case_duplicate",
    }
    try:
        accepted = client.post("/webhooks/razorpay", content=raw, headers=headers)
        duplicate = client.post("/webhooks/razorpay", content=raw, headers=headers)
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert accepted.status_code == 200
    assert duplicate.status_code == 200
    with Session(db_engine) as session:
        assert process_pending(session, SimulatedGateway(7), load()) == 1
        assert session.query(RawEvent).count() == 1
        assert session.query(RecoveryCase).count() == 1
        assert session.query(PaymentAttempt).count() == 1
        assert session.query(AuditEvent).count() == 1
        assert process_pending(session, SimulatedGateway(7), load()) == 0
