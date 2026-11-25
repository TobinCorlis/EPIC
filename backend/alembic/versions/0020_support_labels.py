"""Claim role, review reasons, and invalidation actor backfill.

Revision ID: 0020_support_labels
Revises: 0019_factcheck_followup

Fresh databases already receive the columns from 0001. The actor backfill
still runs: rows whose actor is null take the recorded user id, or
system:factcheck when no user was stored.
"""
import sqlalchemy as sa
from alembic import op

from app.services.factcheck.backfill import backfill_invalidation_actors

revision = "0020_support_labels"
down_revision = "0019_factcheck_followup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    present = {column["name"] for column in sa.inspect(bind).get_columns("claims")}
    with op.batch_alter_table("claims") as batch:
        if "claim_role" not in present:
            batch.add_column(sa.Column("claim_role", sa.String(20), nullable=False, server_default="substantive"))
        if "needs_review_reasons" not in present:
            batch.add_column(sa.Column("needs_review_reasons", sa.Text(), nullable=False, server_default="[]"))
    if "claim_role" not in present or "needs_review_reasons" not in present:
        with op.batch_alter_table("claims") as batch:
            if "claim_role" not in present:
                batch.alter_column("claim_role", server_default=None)
            if "needs_review_reasons" not in present:
                batch.alter_column("needs_review_reasons", server_default=None)
    backfill_invalidation_actors(bind)


def downgrade() -> None:
    bind = op.get_bind()
    present = {column["name"] for column in sa.inspect(bind).get_columns("claims")}
    dropping = [name for name in ("needs_review_reasons", "claim_role") if name in present]
    if dropping:
        with op.batch_alter_table("claims") as batch:
            for name in dropping:
                batch.drop_column(name)
