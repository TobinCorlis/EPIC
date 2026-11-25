"""Actor and reversal fields for automated retractions.

Revision ID: 0019_factcheck_followup
Revises: 0018_source_factcheck

Fresh databases already receive these columns from 0001.
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_factcheck_followup"
down_revision = "0018_source_factcheck"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    present = {column["name"] for column in sa.inspect(bind).get_columns("upstream_invalidations")}
    with op.batch_alter_table("upstream_invalidations") as batch:
        if "actor" not in present:
            batch.add_column(sa.Column("actor", sa.String(80), nullable=True))
        if "reversed_reason" not in present:
            batch.add_column(sa.Column("reversed_reason", sa.Text(), nullable=True))
        if "reversed_by_user_id" not in present:
            batch.add_column(sa.Column("reversed_by_user_id", sa.Integer(), nullable=True))
        if "reversed_at" not in present:
            batch.add_column(sa.Column("reversed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    present = {column["name"] for column in sa.inspect(bind).get_columns("upstream_invalidations")}
    dropping = [
        name
        for name in ("reversed_at", "reversed_by_user_id", "reversed_reason", "actor")
        if name in present
    ]
    if dropping:
        with op.batch_alter_table("upstream_invalidations") as batch:
            for name in dropping:
                batch.drop_column(name)
