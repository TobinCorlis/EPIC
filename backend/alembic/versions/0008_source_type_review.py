"""Record whether a source type has been reviewed.

Revision ID: 0008_source_type_review
Revises: 0007_research_not_implemented

Fresh databases already receive these columns from 0001.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_source_type_review"
down_revision = "0007_research_not_implemented"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sources")}
    with op.batch_alter_table("sources") as batch:
        if "source_type_reviewed" not in columns:
            batch.add_column(sa.Column("source_type_reviewed", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "source_type_reviewed_by_user_id" not in columns:
            batch.add_column(sa.Column("source_type_reviewed_by_user_id", sa.Integer(), nullable=True))
        if "source_type_reviewed_at" not in columns:
            batch.add_column(sa.Column("source_type_reviewed_at", sa.DateTime(), nullable=True))
    if "source_type_reviewed" not in columns:
        with op.batch_alter_table("sources") as batch:
            batch.alter_column("source_type_reviewed", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sources")}
    with op.batch_alter_table("sources") as batch:
        for name in ("source_type_reviewed_at", "source_type_reviewed_by_user_id", "source_type_reviewed"):
            if name in columns:
                batch.drop_column(name)
