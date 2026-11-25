"""Repair retraction notices that were stored as retracted papers.

Revision ID: 0023_retraction_direction
Revises: 0022_current_checks

Leaves the audit rows in place. Reverses the bad invalidation with reason
'notice misread as retracted paper' and actor system:factcheck, and replaces
placeholder notice titles when Crossref can be read.
"""
from alembic import op
from sqlalchemy.orm import Session

from app.services.factcheck.backfill import repair_misread_retraction_notices

revision = "0023_retraction_direction"
down_revision = "0022_current_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    repair_misread_retraction_notices(session)
    session.flush()


def downgrade() -> None:
    return None
