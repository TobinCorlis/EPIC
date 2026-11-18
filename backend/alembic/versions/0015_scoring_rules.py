"""Record whether a cited source was found, and flag library entries for review.

Revision ID: 0015_scoring_rules
Revises: 0014_reference_library

Fresh databases already receive these columns from 0001.
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_scoring_rules"
down_revision = "0014_reference_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    source_columns = {column["name"] for column in inspector.get_columns("sources")}
    missing = []
    if "record_status" not in source_columns:
        missing.append(sa.Column("record_status", sa.String(40), nullable=False, server_default="not_checked"))
    if "record_note" not in source_columns:
        missing.append(sa.Column("record_note", sa.Text(), nullable=True))
    if "record_checked_by_user_id" not in source_columns:
        missing.append(sa.Column("record_checked_by_user_id", sa.Integer(), nullable=True))
    if "record_checked_at" not in source_columns:
        missing.append(sa.Column("record_checked_at", sa.DateTime(), nullable=True))
    if missing:
        with op.batch_alter_table("sources") as batch:
            for column in missing:
                batch.add_column(column)
        if "record_status" not in source_columns:
            with op.batch_alter_table("sources") as batch:
                batch.alter_column("record_status", server_default=None)
    entry_columns = {column["name"] for column in inspector.get_columns("reference_entries")}
    if "needs_review" not in entry_columns:
        with op.batch_alter_table("reference_entries") as batch:
            batch.add_column(sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()))
        with op.batch_alter_table("reference_entries") as batch:
            batch.alter_column("needs_review", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    entry_columns = {column["name"] for column in inspector.get_columns("reference_entries")}
    if "needs_review" in entry_columns:
        with op.batch_alter_table("reference_entries") as batch:
            batch.drop_column("needs_review")
    source_columns = {column["name"] for column in inspector.get_columns("sources")}
    dropping = [
        name
        for name in ("record_checked_at", "record_checked_by_user_id", "record_note", "record_status")
        if name in source_columns
    ]
    if dropping:
        with op.batch_alter_table("sources") as batch:
            for name in dropping:
                batch.drop_column(name)
