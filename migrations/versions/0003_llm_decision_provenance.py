"""Persist optional LLM decision provenance and fallback metadata."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_llm_decision_provenance"
down_revision = "0002_payment_rail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("recovery_decisions")}
    for name, length in (
        ("llm_prompt_version", 64),
        ("llm_cache_key", 64),
        ("llm_fallback_reason", 64),
    ):
        if name not in columns:
            op.add_column("recovery_decisions", sa.Column(name, sa.String(length=length), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("recovery_decisions")}
    for name in ("llm_fallback_reason", "llm_cache_key", "llm_prompt_version"):
        if name in columns:
            op.drop_column("recovery_decisions", name)
