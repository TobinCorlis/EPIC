"""Record when a verification is overturned or marked a mistake.

Revision ID: 0011_verification_overturn
Revises: 0010_claim_needs_review
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_verification_overturn"
down_revision = "0010_claim_needs_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    event_columns = {column["name"] for column in sa.inspect(bind).get_columns("verification_events")}
    with op.batch_alter_table("verification_events") as batch:
        if "mistake_reason" not in event_columns:
            batch.add_column(sa.Column("mistake_reason", sa.Text(), nullable=True))
        if "mistake_recorded_at" not in event_columns:
            batch.add_column(sa.Column("mistake_recorded_at", sa.DateTime(), nullable=True))
        if "mistake_recorded_by_user_id" not in event_columns:
            batch.add_column(sa.Column("mistake_recorded_by_user_id", sa.Integer(), nullable=True))
    correction_columns = {column["name"] for column in sa.inspect(bind).get_columns("claim_corrections")}
    if "kind" not in correction_columns:
        with op.batch_alter_table("claim_corrections") as batch:
            batch.add_column(sa.Column("kind", sa.String(length=40), nullable=False, server_default="text"))
        with op.batch_alter_table("claim_corrections") as batch:
            batch.alter_column("kind", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    event_columns = {column["name"] for column in sa.inspect(bind).get_columns("verification_events")}
    with op.batch_alter_table("verification_events") as batch:
        for name in ("mistake_recorded_by_user_id", "mistake_recorded_at", "mistake_reason"):
            if name in event_columns:
                batch.drop_column(name)
    correction_columns = {column["name"] for column in sa.inspect(bind).get_columns("claim_corrections")}
    if "kind" in correction_columns:
        with op.batch_alter_table("claim_corrections") as batch:
            batch.drop_column("kind")
