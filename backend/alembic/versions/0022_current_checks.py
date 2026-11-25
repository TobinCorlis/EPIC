"""Supersede repeated checks and attach quote checks to their claim.

Revision ID: 0022_current_checks
Revises: 0021_supersede_leads

The superseded column already exists. This backfill keeps the latest row
for each source, claim, and check type. Older rows stay for audit.
"""
from alembic import op
from sqlalchemy.orm import Session

from app.services.factcheck.backfill import supersede_older_checks

revision = "0022_current_checks"
down_revision = "0021_supersede_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    supersede_older_checks(session)
    session.flush()


def downgrade() -> None:
    return None
