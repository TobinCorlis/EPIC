"""Add rule-based turn moderation review queue.

Revision ID: 0004_turn_moderation
Revises: 0003_live_debate_turns
"""
from alembic import op
import sqlalchemy as sa
revision = "0004_turn_moderation"
down_revision = "0003_live_debate_turns"
branch_labels = None
depends_on = None

def upgrade():
    bind=op.get_bind(); tables=set(sa.inspect(bind).get_table_names())
    if "turn_moderation_reviews" not in tables:
        op.create_table("turn_moderation_reviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("debate_id", sa.Integer(), sa.ForeignKey("debates.id"), nullable=False),
            sa.Column("participant_id", sa.Integer(), sa.ForeignKey("participants.id"), nullable=False),
            sa.Column("submitted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("rebuttal_target_turn_id", sa.Integer(), sa.ForeignKey("debate_turns.id"), nullable=True),
            sa.Column("analysis_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("moderator_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("moderator_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),)
        for col in ("debate_id","participant_id","submitted_by_user_id","status","created_at"):
            op.create_index(f"ix_turn_moderation_reviews_{col}", "turn_moderation_reviews", [col])

def downgrade():
    op.drop_table("turn_moderation_reviews")
