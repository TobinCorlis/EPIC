"""Mark stale related-work leads superseded without deleting them.

Revision ID: 0021_supersede_leads
Revises: 0020_support_labels

Fresh databases already have the column from 0001. The backfill still runs:
leads below the overlap gate, and older duplicates of the same external id,
are marked superseded. The rows stay for audit.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.services.factcheck.backfill import supersede_stale_leads

revision = "0021_supersede_leads"
down_revision = "0020_support_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    present = {column["name"] for column in sa.inspect(bind).get_columns("source_checks")}
    if "superseded" not in present:
        with op.batch_alter_table("source_checks") as batch:
            batch.add_column(sa.Column("superseded", sa.Boolean(), nullable=False, server_default=sa.false()))
        with op.batch_alter_table("source_checks") as batch:
            batch.alter_column("superseded", server_default=None)
    session = Session(bind=bind)
    supersede_stale_leads(session)
    session.flush()


def downgrade() -> None:
    bind = op.get_bind()
    present = {column["name"] for column in sa.inspect(bind).get_columns("source_checks")}
    if "superseded" in present:
        with op.batch_alter_table("source_checks") as batch:
            batch.drop_column("superseded")
