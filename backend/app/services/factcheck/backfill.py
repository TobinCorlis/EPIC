"""One-time actor backfill for invalidations recorded before the actor column was filled."""
from sqlalchemy import text


def backfill_invalidation_actors(bind) -> None:
    statements = [
        text(
            "UPDATE upstream_invalidations "
            "SET actor = 'user:' || CAST(recorded_by_user_id AS TEXT) "
            "WHERE actor IS NULL AND recorded_by_user_id IS NOT NULL"
        ),
        text(
            "UPDATE upstream_invalidations "
            "SET actor = 'system:factcheck' "
            "WHERE actor IS NULL"
        ),
    ]
    if not hasattr(bind, "execute"):
        with bind.begin() as connection:
            for statement in statements:
                connection.execute(statement)
        return
    for statement in statements:
        bind.execute(statement)
