"""Add a review flag on claims.

Revision ID: 0010_claim_needs_review
Revises: 0009_uncertainty_and_corrections

The flag records that a rule asked for human review. It is not an off-topic finding.
Fresh databases already receive the column from 0001.
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_claim_needs_review"
down_revision = "0009_uncertainty_and_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("claims")}
    if "needs_review" not in columns:
        with op.batch_alter_table("claims") as batch:
            batch.add_column(sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()))
        with op.batch_alter_table("claims") as batch:
            batch.alter_column("needs_review", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("claims")}
    if "needs_review" in columns:
        with op.batch_alter_table("claims") as batch:
            batch.drop_column("needs_review")
