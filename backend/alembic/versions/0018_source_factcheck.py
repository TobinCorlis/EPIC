"""Automated source checks, the verification queue, and the HTTP cache.

Revision ID: 0018_source_factcheck
Revises: 0017_ai_referee

Fresh databases already receive these tables from 0001.
"""
from alembic import op

from app.models.factcheck import FactcheckCache, SourceCheck, VerificationJob

revision = "0018_source_factcheck"
down_revision = "0017_ai_referee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    SourceCheck.__table__.create(bind=bind, checkfirst=True)
    VerificationJob.__table__.create(bind=bind, checkfirst=True)
    FactcheckCache.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    FactcheckCache.__table__.drop(bind=bind, checkfirst=True)
    VerificationJob.__table__.drop(bind=bind, checkfirst=True)
    SourceCheck.__table__.drop(bind=bind, checkfirst=True)
