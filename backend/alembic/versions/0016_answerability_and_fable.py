"""Not-factually-answerable questions, EPIC FABLE, and confidence labels.

Revision ID: 0016_answerability_and_fable
Revises: 0015_scoring_rules

Fresh databases already receive these objects from 0001.
Library versions saved before labels are recomputed from the claims they cite.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.models.fable import (
    FableCanonNote,
    FableLoreItem,
    FableMatchup,
    FableMove,
    FableParticipant,
    FableReasoningStep,
    FableStepLore,
)
from app.models.library import ReferenceEntryVersion

revision = "0016_answerability_and_fable"
down_revision = "0015_scoring_rules"
branch_labels = None
depends_on = None

_TABLES = (
    FableMatchup,
    FableParticipant,
    FableLoreItem,
    FableReasoningStep,
    FableStepLore,
    FableCanonNote,
    FableMove,
)


def _add_answerability(table: str) -> None:
    present = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    with op.batch_alter_table(table) as batch:
        if "answerability" not in present:
            batch.add_column(sa.Column("answerability", sa.String(40), nullable=False, server_default="factual"))
        if "answerability_reason" not in present:
            batch.add_column(sa.Column("answerability_reason", sa.Text(), nullable=True))
    if "answerability" not in present:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("answerability", server_default=None)


def upgrade() -> None:
    _add_answerability("debates")
    _add_answerability("claims")
    bind = op.get_bind()
    for model in _TABLES:
        model.__table__.create(bind=bind, checkfirst=True)
    session = Session(bind=bind)
    from app.services.reference_library import relabel_version_confidence

    for version in session.query(ReferenceEntryVersion).all():
        relabel_version_confidence(session, version)
    session.flush()


def downgrade() -> None:
    bind = op.get_bind()
    for model in reversed(_TABLES):
        model.__table__.drop(bind=bind, checkfirst=True)
    inspector = sa.inspect(bind)
    for table in ("debates", "claims"):
        present = {column["name"] for column in inspector.get_columns(table)}
        dropping = [name for name in ("answerability_reason", "answerability") if name in present]
        if dropping:
            with op.batch_alter_table(table) as batch:
                for name in dropping:
                    batch.drop_column(name)
