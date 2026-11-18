"""Record verification events for verified and archived statuses.

Revision ID: 0005_verification_events
Revises: 0004_turn_moderation

Fresh databases already receive this table from 0001, which creates the
current metadata. This revision covers databases migrated from the
unmodified v1.0-rc2 baseline.
"""
import sqlalchemy as sa
from alembic import op

from app.models.status_history import StatusHistory
from app.models.verification import VerificationEvent
from app.services.legacy_status import demote_legacy_verified_without_events

revision = "0005_verification_events"
down_revision = "0004_turn_moderation"
branch_labels = None
depends_on = None


def _ensure_postgres_labels(labels: tuple[tuple[str, str], ...]) -> None:
    """Commit new enum labels before any later statement uses them.

    PostgreSQL accepts ADD VALUE inside a transaction, but the new label
    cannot be used until that transaction commits.
    """
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        for type_name, value in labels:
            op.execute(sa.text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'"))


def _allow_unknown_confidence(bind) -> None:
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("knowledge_claims")}
    if columns["confidence_score"]["nullable"]:
        return
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.alter_column("confidence_score", existing_type=sa.Float(), nullable=True)


def upgrade() -> None:
    bind = op.get_bind()
    VerificationEvent.__table__.create(bind=bind, checkfirst=True)
    StatusHistory.__table__.create(bind=bind, checkfirst=True)
    _ensure_postgres_labels(
        (
            ("verificationstatus", "unverified"),
            ("verificationstatus", "archived"),
            ("knowledgestatus", "unverified"),
            ("knowledgestatus", "archived"),
        )
    )
    _allow_unknown_confidence(bind)
    demote_legacy_verified_without_events(bind)


def downgrade() -> None:
    # The baseline build cannot read unverified/archived. Do not put verified
    # back: this revision removed that label when no verification event existed,
    # and downgrade drops the event log that could justify it.
    if "argument_nodes" in sa.inspect(op.get_bind()).get_table_names():
        op.execute(
            sa.text(
                """
                UPDATE argument_nodes
                SET verification_status = 'unreviewed'
                WHERE verification_status IN ('unverified', 'archived', 'verified')
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE knowledge_claims
                SET status = 'candidate'
                WHERE status IN ('unverified', 'archived', 'verified')
                """
            )
        )
    # rc2 cannot store NULL confidence. Restoring a number here is only so the
    # old column can be NOT NULL again. It does not restore verified.
    op.execute(sa.text("UPDATE knowledge_claims SET confidence_score = 0 WHERE confidence_score IS NULL"))
    confidence = next(
        column
        for column in sa.inspect(op.get_bind()).get_columns("knowledge_claims")
        if column["name"] == "confidence_score"
    )
    if confidence["nullable"]:
        with op.batch_alter_table("knowledge_claims") as batch:
            batch.alter_column("confidence_score", existing_type=sa.Float(), nullable=False)
    StatusHistory.__table__.drop(bind=op.get_bind(), checkfirst=True)
    VerificationEvent.__table__.drop(bind=op.get_bind(), checkfirst=True)
