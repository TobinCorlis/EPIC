"""Add durable live debate turn state.

Revision ID: 0003_live_debate_turns
Revises: 0002_realtime_collaboration
"""
from alembic import op
import sqlalchemy as sa
revision = "0003_live_debate_turns"
down_revision = "0002_realtime_collaboration"
branch_labels = None
depends_on = None

def upgrade():
    bind=op.get_bind(); tables=set(sa.inspect(bind).get_table_names())
    if "debate_room_states" not in tables:
        op.create_table("debate_room_states",
            sa.Column("debate_id", sa.Integer(), sa.ForeignKey("debates.id"), primary_key=True),
            sa.Column("current_participant_id", sa.Integer(), sa.ForeignKey("participants.id"), nullable=True),
            sa.Column("turn_duration_seconds", sa.Integer(), nullable=False, server_default="300"),
            sa.Column("turn_started_at", sa.DateTime(), nullable=True),
            sa.Column("turn_sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),)
        op.create_index("ix_debate_room_states_current_participant_id", "debate_room_states", ["current_participant_id"])
    if "debate_turns" not in tables:
        op.create_table("debate_turns",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("debate_id", sa.Integer(), sa.ForeignKey("debates.id"), nullable=False),
            sa.Column("participant_id", sa.Integer(), sa.ForeignKey("participants.id"), nullable=False),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("submitted_at", sa.DateTime(), nullable=False),)
        op.create_index("ix_debate_turns_debate_id", "debate_turns", ["debate_id"])
        op.create_index("ix_debate_turns_participant_id", "debate_turns", ["participant_id"])
        op.create_index("ix_debate_turns_sequence_number", "debate_turns", ["sequence_number"])

def downgrade():
    op.drop_table("debate_turns"); op.drop_table("debate_room_states")
