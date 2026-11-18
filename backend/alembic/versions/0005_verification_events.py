"""Record verification events for verified and archived statuses.

Revision ID: 0005_verification_events
Revises: 0004_turn_moderation

Fresh databases already receive this table from 0001, which creates the
current metadata. This revision covers databases migrated from the
unmodified v1.0-rc2 baseline.
"""
import sqlalchemy as sa
from alembic import op

from app.models.verification import VerificationEvent

revision = "0005_verification_events"
down_revision = "0004_turn_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    VerificationEvent.__table__.create(bind=bind, checkfirst=True)
    if bind.dialect.name != "postgresql":
        return
    # Existing native enums from the baseline do not include these labels.
    for type_name, value in (
        ("verificationstatus", "unverified"),
        ("verificationstatus", "archived"),
        ("knowledgestatus", "unverified"),
        ("knowledgestatus", "archived"),
    ):
        op.execute(sa.text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'"))


def downgrade() -> None:
    VerificationEvent.__table__.drop(bind=op.get_bind(), checkfirst=True)
