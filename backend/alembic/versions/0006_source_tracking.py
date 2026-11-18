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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    source_columns = {column["name"]: column for column in inspector.get_columns("sources")}
    with op.batch_alter_table("sources") as batch:
        if "document_reference" not in source_columns:
            batch.add_column(sa.Column("document_reference", sa.String(length=1000), nullable=True))
        if "verification_status" not in source_columns:
            batch.add_column(
                sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="unverified")
            )
        if "archive_url" not in source_columns:
            batch.add_column(sa.Column("archive_url", sa.String(length=2048), nullable=True))
        if "archived_at" not in source_columns:
            batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        if source_columns["url"]["nullable"] is False:
            batch.alter_column("url", existing_type=sa.String(length=2048), nullable=True)
    if "verification_status" not in source_columns:
        with op.batch_alter_table("sources") as batch:
            batch.alter_column("verification_status", server_default=None)

    evidence_columns = {column["name"] for column in inspector.get_columns("claim_evidence")}
    if "claim_supported" not in evidence_columns:
        with op.batch_alter_table("claim_evidence") as batch:
            batch.add_column(sa.Column("claim_supported", sa.Text(), nullable=False, server_default=""))
        with op.batch_alter_table("claim_evidence") as batch:
            batch.alter_column("claim_supported", server_default=None)

    check_names = {item.get("name") for item in inspector.get_check_constraints("sources")}
    if "ck_sources_locator" not in check_names:
        op.create_check_constraint(
            "ck_sources_locator",
            "sources",
            "url IS NOT NULL OR document_reference IS NOT NULL",
        )

    if bind.dialect.name == "postgresql":
        op.execute(sa.text("ALTER TYPE verificationsubject ADD VALUE IF NOT EXISTS 'source'"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    check_names = {item.get("name") for item in inspector.get_check_constraints("sources")}
    if "ck_sources_locator" in check_names:
        op.drop_constraint("ck_sources_locator", "sources", type_="check")
    evidence_columns = {column["name"] for column in inspector.get_columns("claim_evidence")}
    source_columns = {column["name"] for column in inspector.get_columns("sources")}
    with op.batch_alter_table("claim_evidence") as batch:
        if "claim_supported" in evidence_columns:
            batch.drop_column("claim_supported")
    with op.batch_alter_table("sources") as batch:
        for name in ("archived_at", "archive_url", "verification_status", "document_reference"):
            if name in source_columns:
                batch.drop_column(name)
        batch.alter_column("url", existing_type=sa.String(length=2048), nullable=False)
