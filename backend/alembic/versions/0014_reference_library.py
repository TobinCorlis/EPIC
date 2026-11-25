"""Reference library, re-evaluation requests, and upstream invalidation.

Revision ID: 0014_reference_library
Revises: 0013_scope_review

Fresh databases already receive these tables from 0001.
"""
import sqlalchemy as sa
from alembic import op

from app.models.library import (
    LibraryPoint,
    ReferenceEntry,
    ReferenceEntryClaim,
    ReferenceEntryDebate,
    ReferenceEntrySource,
    ReferenceEntryVerification,
    ReferenceEntryVersion,
    ReevaluationRequest,
    UpstreamInvalidation,
)

revision = "0014_reference_library"
down_revision = "0013_scope_review"
branch_labels = None
depends_on = None

_TABLES = (
    ReferenceEntry,
    ReferenceEntryVersion,
    ReferenceEntryClaim,
    ReferenceEntrySource,
    ReferenceEntryVerification,
    ReferenceEntryDebate,
    LibraryPoint,
    ReevaluationRequest,
    UpstreamInvalidation,
)


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("debates")}
    if "library_stale" not in columns:
        with op.batch_alter_table("debates") as batch:
            batch.add_column(sa.Column("library_stale", sa.Boolean(), nullable=False, server_default=sa.false()))
        with op.batch_alter_table("debates") as batch:
            batch.alter_column("library_stale", server_default=None)
    for model in _TABLES:
        model.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for model in reversed(_TABLES):
        model.__table__.drop(bind=bind, checkfirst=True)
    columns = {column["name"] for column in sa.inspect(bind).get_columns("debates")}
    if "library_stale" in columns:
        with op.batch_alter_table("debates") as batch:
            batch.drop_column("library_stale")
