from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime.

    Columns in this schema are timezone-naive. The value comes from an
    aware UTC clock with the timezone removed so existing comparisons keep
    working.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
