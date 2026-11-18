"""Add document references, source verification fields, and claim_supported.

Revision ID: 0006_source_tracking
Revises: 0005_verification_events

Fresh databases already receive these columns from 0001. This revision
covers databases migrated from an earlier revision.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_source_tracking"
down_revision = "0005_verification_events"
branch_labels = None
depends_on = None

LEGACY_CLAIM_SUPPORTED = "legacy: not recorded"


def _source_status_type(bind):
    if bind.dialect.name == "postgresql":
        return sa.Enum("unverified", "verified", "archived", name="sourceverificationstatus")
    return sa.String(length=32)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    source_columns = {column["name"]: column for column in inspector.get_columns("sources")}
    check_names = {item.get("name") for item in inspector.get_check_constraints("sources")}
    added_status = "verification_status" not in source_columns
    if added_status and bind.dialect.name == "postgresql":
        _source_status_type(bind).create(bind, checkfirst=True)

    if (
        added_status
        or "document_reference" not in source_columns
        or "archive_url" not in source_columns
        or "archived_at" not in source_columns
        or source_columns["url"]["nullable"] is False
        or "ck_sources_locator" not in check_names
    ):
        with op.batch_alter_table("sources") as batch:
            if "document_reference" not in source_columns:
                batch.add_column(sa.Column("document_reference", sa.String(length=1000), nullable=True))
            if added_status:
                batch.add_column(
                    sa.Column(
                        "verification_status",
                        _source_status_type(bind),
                        nullable=False,
                        server_default="unverified",
                    )
                )
            if "archive_url" not in source_columns:
                batch.add_column(sa.Column("archive_url", sa.String(length=2048), nullable=True))
            if "archived_at" not in source_columns:
                batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
            if source_columns["url"]["nullable"] is False:
                batch.alter_column("url", existing_type=sa.String(length=2048), nullable=True)
            if "ck_sources_locator" not in check_names:
                batch.create_check_constraint(
                    "ck_sources_locator",
                    "url IS NOT NULL OR document_reference IS NOT NULL",
                )
    if added_status:
        with op.batch_alter_table("sources") as batch:
            batch.alter_column("verification_status", server_default=None)

    evidence_columns = {column["name"] for column in inspector.get_columns("claim_evidence")}
    if "claim_supported" not in evidence_columns:
        # Existing links have no recorded claim text. The placeholder says so.
        # It is not a paraphrase of the claim or the excerpt.
        with op.batch_alter_table("claim_evidence") as batch:
            batch.add_column(
                sa.Column("claim_supported", sa.Text(), nullable=False, server_default=LEGACY_CLAIM_SUPPORTED)
            )
        with op.batch_alter_table("claim_evidence") as batch:
            batch.alter_column("claim_supported", server_default=None)

    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(sa.text("ALTER TYPE verificationsubject ADD VALUE IF NOT EXISTS 'source'"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    check_names = {item.get("name") for item in inspector.get_check_constraints("sources")}
    evidence_columns = {column["name"] for column in inspector.get_columns("claim_evidence")}
    source_columns = {column["name"] for column in inspector.get_columns("sources")}
    if "claim_supported" in evidence_columns:
        with op.batch_alter_table("claim_evidence") as batch:
            batch.drop_column("claim_supported")
    with op.batch_alter_table("sources") as batch:
        if "ck_sources_locator" in check_names:
            batch.drop_constraint("ck_sources_locator", type_="check")
        for name in ("archived_at", "archive_url", "verification_status", "document_reference"):
            if name in source_columns:
                batch.drop_column(name)
        if "url" in source_columns:
            batch.alter_column("url", existing_type=sa.String(length=2048), nullable=False)
    if bind.dialect.name == "postgresql":
        sa.Enum(name="sourceverificationstatus").drop(bind, checkfirst=True)
