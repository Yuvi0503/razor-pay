"""Add optional issuer/bank rail dimension for outage detection."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_payment_rail"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("payment_attempts")}
    if "issuer_or_bank" not in columns:
        op.add_column("payment_attempts", sa.Column("issuer_or_bank", sa.String(length=128), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("payment_attempts")}
    if "issuer_or_bank" in columns:
        op.drop_column("payment_attempts", "issuer_or_bank")
