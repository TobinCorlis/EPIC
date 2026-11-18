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


def _demote_verified_without_events() -> None:
    """A baseline 'verified' flag is not a verification event.

    Rows stay unverified unless verification_events already records the
    decision. Confidence is left unchanged; it is not a verification.
    """
    op.execute(
        sa.text(
            """
            UPDATE argument_nodes
            SET verification_status = 'unverified'
            WHERE verification_status = 'verified'
              AND NOT EXISTS (
                SELECT 1 FROM verification_events
                WHERE subject_type = 'argument_node'
                  AND subject_id = argument_nodes.id
                  AND result_status = 'verified'
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE knowledge_claims
            SET status = 'unverified'
            WHERE status = 'verified'
              AND NOT EXISTS (
                SELECT 1 FROM verification_events
                WHERE subject_type = 'knowledge_claim'
                  AND subject_id = knowledge_claims.id
                  AND result_status = 'verified'
              )
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    VerificationEvent.__table__.create(bind=bind, checkfirst=True)
    _ensure_postgres_labels(
        (
            ("verificationstatus", "unverified"),
            ("verificationstatus", "archived"),
            ("knowledgestatus", "unverified"),
            ("knowledgestatus", "archived"),
        )
    )
    _demote_verified_without_events()


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
    VerificationEvent.__table__.drop(bind=op.get_bind(), checkfirst=True)
