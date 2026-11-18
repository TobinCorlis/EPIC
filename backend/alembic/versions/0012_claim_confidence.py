"""Store auditable claim-confidence breakdowns.

Revision ID: 0012_claim_confidence
Revises: 0011_verification_overturn
"""
from alembic import op

from app.models.confidence import ClaimConfidenceAssessment

revision = "0012_claim_confidence"
down_revision = "0011_verification_overturn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ClaimConfidenceAssessment.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    ClaimConfidenceAssessment.__table__.drop(bind=op.get_bind(), checkfirst=True)
