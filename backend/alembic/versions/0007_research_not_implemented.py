"""Add the not_implemented research job status.

Revision ID: 0007_research_not_implemented
Revises: 0006_source_tracking

SQLite stores the status as a string. PostgreSQL uses a native enum created
by the baseline migration, so an upgraded database needs the new label.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_research_not_implemented"
down_revision = "0006_source_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("ALTER TYPE researchjobstatus ADD VALUE IF NOT EXISTS 'not_implemented'"))


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum label without recreating the type.
    pass
