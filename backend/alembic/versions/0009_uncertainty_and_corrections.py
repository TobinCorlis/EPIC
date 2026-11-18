"""Add claim uncertainty and the correction log.

Revision ID: 0009_uncertainty_and_corrections
Revises: 0008_source_type_review

Fresh databases already receive these objects from 0001.
"""
import sqlalchemy as sa
from alembic import op

from app.models.correction import ClaimCorrection

revision = "0009_uncertainty_and_corrections"
down_revision = "0008_source_type_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("claims", "knowledge_claims"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "uncertainty" not in columns:
            op.add_column(table, sa.Column("uncertainty", sa.Text(), nullable=True))
    ClaimCorrection.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    ClaimCorrection.__table__.drop(bind=bind, checkfirst=True)
    inspector = sa.inspect(bind)
    for table in ("claims", "knowledge_claims"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "uncertainty" in columns:
            with op.batch_alter_table(table) as batch:
                batch.drop_column("uncertainty")
