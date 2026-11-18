"""Store measured scope and rule-based scope review flags.

Revision ID: 0013_scope_review
Revises: 0012_claim_confidence

Fresh databases already receive these columns and the flag table from 0001.
"""
import sqlalchemy as sa
from alembic import op

from app.models.scope import ScopeReviewFlag

revision = "0013_scope_review"
down_revision = "0012_claim_confidence"
branch_labels = None
depends_on = None

_SCOPE = (
    ("scope_population", sa.String(300)),
    ("scope_timeframe", sa.String(300)),
    ("scope_geography", sa.String(300)),
    ("scope_metric", sa.String(300)),
    ("scope_study_type", sa.String(80)),
    ("scope_sample_size", sa.Integer()),
)
_QUESTION = (
    ("question_population", sa.String(300)),
    ("question_timeframe", sa.String(300)),
    ("question_geography", sa.String(300)),
    ("question_metric", sa.String(300)),
)
_CLAIM = (
    ("scope_population", sa.String(300)),
    ("scope_timeframe", sa.String(300)),
    ("scope_geography", sa.String(300)),
    ("scope_metric", sa.String(300)),
)


def _add_missing(table: str, columns: tuple[tuple[str, sa.types.TypeEngine], ...]) -> None:
    bind = op.get_bind()
    present = {column["name"] for column in sa.inspect(bind).get_columns(table)}
    missing = [(name, kind) for name, kind in columns if name not in present]
    if not missing:
        return
    with op.batch_alter_table(table) as batch:
        for name, kind in missing:
            batch.add_column(sa.Column(name, kind, nullable=True))


def upgrade() -> None:
    _add_missing("sources", _SCOPE)
    _add_missing("claim_evidence", _SCOPE)
    _add_missing("claims", _CLAIM)
    _add_missing("debates", _QUESTION)
    ScopeReviewFlag.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    ScopeReviewFlag.__table__.drop(bind=bind, checkfirst=True)
    inspector = sa.inspect(bind)
    for table, columns in (
        ("sources", _SCOPE),
        ("claim_evidence", _SCOPE),
        ("claims", _CLAIM),
        ("debates", _QUESTION),
    ):
        present = {column["name"] for column in inspector.get_columns(table)}
        dropping = [name for name, _kind in columns if name in present]
        if not dropping:
            continue
        with op.batch_alter_table(table) as batch:
            for name in dropping:
                batch.drop_column(name)
