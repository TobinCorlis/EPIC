"""Add invitations, debate events, and participant account binding.

Revision ID: 0002_realtime_collaboration
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_realtime_collaboration"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    participant_columns = {c["name"] for c in inspector.get_columns("participants")}
    if "user_id" not in participant_columns:
        with op.batch_alter_table("participants") as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch.create_index("ix_participants_user_id", ["user_id"])
            batch.create_foreign_key("fk_participants_user_id", "users", ["user_id"], ["id"])

    if "debate_invitations" not in tables:
        op.create_table(
            "debate_invitations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("debate_id", sa.Integer(), sa.ForeignKey("debates.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("invited_email", sa.String(320), nullable=True),
            sa.Column("participant_role", sa.String(40), nullable=False),
            sa.Column("side", sa.String(40), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("max_uses", sa.Integer(), nullable=False),
            sa.Column("use_count", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_debate_invitations_debate_id", "debate_invitations", ["debate_id"])
        op.create_index("ix_debate_invitations_token_hash", "debate_invitations", ["token_hash"], unique=True)

    if "debate_events" not in tables:
        op.create_table(
            "debate_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("debate_id", sa.Integer(), sa.ForeignKey("debates.id"), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_debate_events_debate_id", "debate_events", ["debate_id"])
        op.create_index("ix_debate_events_created_at", "debate_events", ["created_at"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "debate_events" in tables:
        op.drop_table("debate_events")
    if "debate_invitations" in tables:
        op.drop_table("debate_invitations")
    columns = {c["name"] for c in inspector.get_columns("participants")}
    if "user_id" in columns:
        with op.batch_alter_table("participants") as batch:
            batch.drop_column("user_id")
