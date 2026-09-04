"""Create the revenue recovery persistence schema.

Revision ID: 0001_initial_schema
Revises:
"""

from alembic import op

from backend.db import models as _models  # noqa: F401 - register ORM tables
from backend.db.base import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_append_only_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER payment_attempts_append_only
            BEFORE UPDATE OR DELETE ON payment_attempts
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
        op.execute("DROP TRIGGER IF EXISTS payment_attempts_append_only ON payment_attempts")
        op.execute("DROP FUNCTION IF EXISTS reject_append_only_mutation()")
    Base.metadata.drop_all(bind=bind)
