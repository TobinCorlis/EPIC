"""Referee rulings, room settings, and the ruling history.

Revision ID: 0017_ai_referee
Revises: 0016_answerability_and_fable

Fresh databases already receive these objects from 0001.
"""
import sqlalchemy as sa
from alembic import op

from app.models.fable import FableRuling

revision = "0017_ai_referee"
down_revision = "0016_answerability_and_fable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    present = {column["name"] for column in sa.inspect(bind).get_columns("fable_matchups")}
    with op.batch_alter_table("fable_matchups") as batch:
        if "referee_mode" not in present:
            batch.add_column(sa.Column("referee_mode", sa.String(40), nullable=False, server_default="ai_suggest"))
        if "canon_only" not in present:
            batch.add_column(sa.Column("canon_only", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "referee_mode" not in present:
        with op.batch_alter_table("fable_matchups") as batch:
            batch.alter_column("referee_mode", server_default=None)
            batch.alter_column("canon_only", server_default=None)
    FableRuling.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    FableRuling.__table__.drop(bind=bind, checkfirst=True)
    present = {column["name"] for column in sa.inspect(bind).get_columns("fable_matchups")}
    dropping = [name for name in ("canon_only", "referee_mode") if name in present]
    if dropping:
        with op.batch_alter_table("fable_matchups") as batch:
            for name in dropping:
                batch.drop_column(name)
