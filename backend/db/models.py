from datetime import datetime
from typing import TypeAlias

from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum

from backend.domain.enums import (
    ActionType,
    ApprovalDecision,
    AuditActor,
    CaseClass,
    CaseState,
    ClassifiedBy,
    ConsentChannel,
    ConsentState,
    DecisionSource,
    FailureCategory,
    GeneratedBy,
    InitiatedBy,
    MessageChannel,
    OrderStatus,
    PaymentAttemptStatus,
    Recoverability,
    RecoveryActionState,
    RecoveryResolution,
    VerdictType,
)

from .base import Base, CreatedAtMixin, UpdatedAtMixin, new_id, utcnow

JsonDocument: TypeAlias = dict[str, object] | list[object]


def enum_type(enum_cls: type, name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda enum: [member.value for member in enum],
        native_enum=True,
        validate_strings=True,
    )


def json_type() -> JSONB:
    return JSONB().with_variant(JSON(), "sqlite")


def array_type() -> ARRAY[str]:
    return ARRAY(Text()).with_variant(JSON(), "sqlite")


class Merchant(CreatedAtMixin, Base):
    __tablename__ = "merchants"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class Customer(CreatedAtMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("merchant_id", "external_ref"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    email_hash: Mapped[str | None] = mapped_column(String(128))
    phone_hash: Mapped[str | None] = mapped_column(String(128))


class CustomerConsent(CreatedAtMixin, Base):
    __tablename__ = "customer_consent"
    __table_args__ = (UniqueConstraint("customer_id", "channel"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    channel: Mapped[ConsentChannel] = mapped_column(
        enum_type(ConsentChannel, "consent_channel"), nullable=False
    )
    state: Mapped[ConsentState] = mapped_column(
        enum_type(ConsentState, "consent_state"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)


class Order(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount_paise >= 0", name="orders_amount_paise_nonnegative"),
        Index("ix_orders_merchant_created_at", "merchant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    provider_order_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        enum_type(OrderStatus, "order_status"), nullable=False, default=OrderStatus.CREATED
    )


class Subscription(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (CheckConstraint("amount_paise >= 0", name="subscriptions_amount_paise_nonnegative"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    provider_sub_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    next_charge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mandate_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PaymentAttempt(CreatedAtMixin, Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint(
            "order_id IS NOT NULL OR subscription_id IS NOT NULL",
            name="payment_attempts_parent_required",
        ),
        CheckConstraint("amount_paise >= 0", name="payment_attempts_amount_paise_nonnegative"),
        Index(
            "uq_payment_attempts_provider_payment_id",
            "provider_payment_id",
            unique=True,
            postgresql_where=text("provider_payment_id IS NOT NULL"),
            sqlite_where=text("provider_payment_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"))
    subscription_id: Mapped[str | None] = mapped_column(ForeignKey("subscriptions.id"))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255))
    method: Mapped[str | None] = mapped_column(String(64))
    issuer_or_bank: Mapped[str | None] = mapped_column(String(128))
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[PaymentAttemptStatus] = mapped_column(
        enum_type(PaymentAttemptStatus, "payment_attempt_status"), nullable=False
    )
    raw_error_code: Mapped[str | None] = mapped_column(String(128))
    raw_error_reason: Mapped[str | None] = mapped_column(String(255))
    raw_error_description: Mapped[str | None] = mapped_column(Text)
    failure_category: Mapped[FailureCategory | None] = mapped_column(
        enum_type(FailureCategory, "failure_category")
    )
    classified_by: Mapped[ClassifiedBy | None] = mapped_column(
        enum_type(ClassifiedBy, "classified_by")
    )
    initiated_by: Mapped[InitiatedBy] = mapped_column(
        enum_type(InitiatedBy, "initiated_by"), nullable=False
    )
    recovery_action_id: Mapped[str | None] = mapped_column(ForeignKey("recovery_actions.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecoveryCase(CreatedAtMixin, Base):
    __tablename__ = "recovery_cases"
    __table_args__ = (
        CheckConstraint("amount_at_risk_paise >= 0", name="recovery_cases_amount_paise_nonnegative"),
        Index(
            "uq_recovery_cases_open_order",
            "order_id",
            unique=True,
            postgresql_where=text("order_id IS NOT NULL AND resolved_at IS NULL"),
            sqlite_where=text("order_id IS NOT NULL AND resolved_at IS NULL"),
        ),
        Index("ix_recovery_cases_next_action_at", "next_action_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"))
    subscription_id: Mapped[str | None] = mapped_column(ForeignKey("subscriptions.id"))
    case_class: Mapped[CaseClass] = mapped_column(
        enum_type(CaseClass, "case_class"), nullable=False
    )
    amount_at_risk_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    failure_category: Mapped[FailureCategory] = mapped_column(
        enum_type(FailureCategory, "failure_category"), nullable=False
    )
    recoverability: Mapped[Recoverability] = mapped_column(
        enum_type(Recoverability, "recoverability"), nullable=False
    )
    state: Mapped[CaseState] = mapped_column(
        enum_type(CaseState, "case_state"), nullable=False, default=CaseState.OPEN
    )
    contacts_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    charge_attempts_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    experiment_arm: Mapped[str | None] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[RecoveryResolution | None] = mapped_column(
        enum_type(RecoveryResolution, "recovery_resolution")
    )
    recovered_amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    recovered_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("payment_attempts.id"))


class RecoveryDecision(CreatedAtMixin, Base):
    __tablename__ = "recovery_decisions"
    __table_args__ = (CheckConstraint("llm_confidence >= 0 AND llm_confidence <= 1", name="recovery_decisions_confidence_range"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), nullable=False)
    proposed_action: Mapped[ActionType] = mapped_column(
        enum_type(ActionType, "action_type"), nullable=False
    )
    proposed_delay_minutes: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[DecisionSource] = mapped_column(
        enum_type(DecisionSource, "decision_source"), nullable=False
    )
    rule_id: Mapped[str | None] = mapped_column(String(64))
    reason_codes: Mapped[list[str] | None] = mapped_column(array_type())
    llm_model: Mapped[str | None] = mapped_column(String(128))
    llm_prompt_version: Mapped[str | None] = mapped_column(String(64))
    llm_cache_key: Mapped[str | None] = mapped_column(String(64))
    llm_fallback_reason: Mapped[str | None] = mapped_column(String(64))
    llm_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    llm_raw_response: Mapped[JsonDocument | None] = mapped_column(json_type())
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_snapshot: Mapped[JsonDocument] = mapped_column(json_type(), nullable=False)


class PolicyEvaluation(CreatedAtMixin, Base):
    __tablename__ = "policy_evaluations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    decision_id: Mapped[str] = mapped_column(ForeignKey("recovery_decisions.id"), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), nullable=False)
    verdict: Mapped[VerdictType] = mapped_column(
        enum_type(VerdictType, "verdict_type"), nullable=False
    )
    final_action: Mapped[ActionType | None] = mapped_column(enum_type(ActionType, "action_type"))
    rules_fired: Mapped[JsonDocument] = mapped_column(json_type(), nullable=False)
    policy_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RecoveryAction(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "recovery_actions"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("ix_recovery_actions_scheduled_for", "scheduled_for"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), nullable=False)
    policy_evaluation_id: Mapped[str] = mapped_column(ForeignKey("policy_evaluations.id"), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(enum_type(ActionType, "action_type"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[RecoveryActionState] = mapped_column(
        enum_type(RecoveryActionState, "recovery_action_state"), nullable=False
    )
    skip_reason: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    result: Mapped[JsonDocument | None] = mapped_column(json_type())


class HumanApproval(CreatedAtMixin, Base):
    __tablename__ = "human_approvals"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), nullable=False)
    decision_id: Mapped[str] = mapped_column(ForeignKey("recovery_decisions.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[ApprovalDecision | None] = mapped_column(
        enum_type(ApprovalDecision, "approval_decision")
    )
    note: Mapped[str | None] = mapped_column(Text)


class OutboundMessage(CreatedAtMixin, Base):
    __tablename__ = "outbound_messages"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), nullable=False)
    action_id: Mapped[str] = mapped_column(ForeignKey("recovery_actions.id"), nullable=False)
    channel: Mapped[MessageChannel] = mapped_column(
        enum_type(MessageChannel, "message_channel"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rendered_subject: Mapped[str | None] = mapped_column(Text)
    rendered_body: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[GeneratedBy] = mapped_column(
        enum_type(GeneratedBy, "generated_by"), nullable=False
    )


class AuditEvent(CreatedAtMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_case_occurred_at", "case_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("recovery_cases.id"))
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[AuditActor] = mapped_column(enum_type(AuditActor, "audit_actor"), nullable=False)
    payload: Mapped[JsonDocument | None] = mapped_column(json_type())
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RawEvent(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("provider_event_id"),
        Index("ix_raw_events_received_at", "received_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(128))
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[JsonDocument] = mapped_column(json_type(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


__all__ = [
    "AuditEvent",
    "Customer",
    "CustomerConsent",
    "HumanApproval",
    "Merchant",
    "Order",
    "OutboundMessage",
    "PaymentAttempt",
    "PolicyEvaluation",
    "RawEvent",
    "RecoveryAction",
    "RecoveryCase",
    "RecoveryDecision",
    "Subscription",
]
