"""Read stored checks. This module does not call the network."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.factcheck import SourceCheck

BIBLIOGRAPHIC = {"crossref", "pubmed", "openalex", "federal_register", "govinfo", "courtlistener"}
DEFINITIVE = {"crossref", "pubmed", "federal_register", "govinfo", "courtlistener"}
NOT_CHECKED_DETAIL = "No automated source check has been recorded. That is not a verification."


def _latest(rows: list[SourceCheck], names: set[str] | None = None) -> dict[str, SourceCheck]:
    latest: dict[str, SourceCheck] = {}
    for row in rows:
        if names is not None and row.checker_name not in names:
            continue
        latest[row.checker_name] = row
    return latest


def source_rows(db: Session, source_id: int) -> list[SourceCheck]:
    return (
        db.query(SourceCheck)
        .filter(SourceCheck.source_id == source_id)
        .order_by(SourceCheck.id)
        .all()
    )


def findability_for_source(db: Session, source_id: int) -> str:
    """Roll up the latest check from each adapter.

    A DOI, PMID, or official identifier that is missing is not findable.
    A failed request is check_failed, not a missing record and not a confirmation.
    An OpenAlex miss does not override a page that was actually fetched.
    """
    latest = _latest(source_rows(db, source_id), BIBLIOGRAPHIC | {"url"})
    if not latest:
        return "not_checked"
    definitive = [row for name, row in latest.items() if name in DEFINITIVE]
    openalex = latest.get("openalex")
    url = latest.get("url")
    if any(row.result == "found" for row in definitive):
        return "found"
    if openalex is not None and openalex.result == "found":
        return "found"
    if definitive and all(row.result == "not_found" for row in definitive):
        return "not_findable"
    if any(row.result == "check_failed" for row in definitive):
        return "check_failed"
    if openalex is not None and openalex.result == "low_confidence":
        return "low_confidence"
    page_found = url is not None and url.result == "fetched" and url.http_status is not None and url.http_status < 400
    if page_found:
        return "found"
    if url is not None and url.result == "not_found" and (openalex is None or openalex.result == "not_found"):
        return "not_findable"
    if openalex is not None and openalex.result == "not_found" and url is None:
        return "not_findable"
    if any(row.result == "check_failed" for row in latest.values()):
        return "check_failed"
    return "not_checked"


def has_retraction(db: Session, source_id: int) -> bool:
    latest = _latest(source_rows(db, source_id), {"retraction"})
    row = latest.get("retraction")
    return row is not None and row.result == "retracted"


def provenance_line(db: Session, source_id: int) -> str | None:
    rows = [row for row in source_rows(db, source_id) if row.checker_name in BIBLIOGRAPHIC | {"url"}]
    if not rows:
        return None
    row = rows[-1]
    response = row.response_id or "none"
    return (
        f"Check {row.checker_name} {row.checker_version} via {row.api_name}, "
        f"query {row.query}, response {response}, at {row.created_at.isoformat()}."
    )


def describe_source(db: Session, source_id: int) -> tuple[str, str]:
    status = findability_for_source(db, source_id)
    line = provenance_line(db, source_id)
    detail = {
        "not_checked": NOT_CHECKED_DETAIL,
        "found": "A lookup found the cited source. This is not a verification.",
        "not_findable": "A lookup did not find the cited source. A claim that rests only on it scores 0 and is Unsupported.",
        "check_failed": "A lookup failed. The source was not marked verified and was not marked missing.",
        "low_confidence": "A title search matched too weakly to confirm the source. It is flagged for review and was not auto-confirmed.",
    }[status if status in {"not_checked", "found", "not_findable", "check_failed", "low_confidence"} else "not_checked"]
    if status == "found":
        reported = "checked"
    else:
        reported = status
    if line:
        detail = f"{detail} {line}"
    if has_retraction(db, source_id):
        detail = f"A retraction check is recorded. {detail}"
    return reported, detail


def describe_sources(db: Session, source_ids: list[int]) -> tuple[str, str]:
    if not source_ids:
        return "not_checked", NOT_CHECKED_DETAIL
    statuses = [findability_for_source(db, source_id) for source_id in source_ids]
    if all(status == "not_checked" for status in statuses):
        return "not_checked", NOT_CHECKED_DETAIL
    if any(status == "not_findable" for status in statuses):
        status, detail = "not_findable", "A lookup did not find a cited source. A claim that rests only on it scores 0 and is Unsupported."
    elif any(status == "check_failed" for status in statuses):
        status, detail = "check_failed", "A lookup failed. Nothing was marked verified or missing because of that failure."
    elif any(status == "low_confidence" for status in statuses):
        status, detail = "low_confidence", "A title search matched too weakly to confirm a cited source. It was not auto-confirmed."
    elif any(status == "found" for status in statuses):
        status, detail = "checked", "A lookup found a cited source. This is not a verification."
    else:
        status, detail = "not_checked", NOT_CHECKED_DETAIL
    line = next((provenance_line(db, source_id) for source_id in source_ids if provenance_line(db, source_id)), None)
    if line:
        detail = f"{detail} {line}"
    return status, detail


def review_signal(db: Session, source_id: int) -> bool:
    """True when a stored check should be looked at by a person."""
    latest = _latest(source_rows(db, source_id))
    return any(row.result in {"mismatch", "retracted", "corrected", "expression_of_concern", "low_confidence", "check_failed", "not_findable"} for row in latest.values())


def latest_quote_results(db: Session, citation_ids: list[int]) -> set[str]:
    if not citation_ids:
        return set()
    rows = (
        db.query(SourceCheck)
        .filter(SourceCheck.citation_id.in_(citation_ids), SourceCheck.checker_name == "quote")
        .order_by(SourceCheck.id)
        .all()
    )
    latest: dict[int, SourceCheck] = {}
    for row in rows:
        if row.citation_id is not None:
            latest[row.citation_id] = row
    return {row.result for row in latest.values()}
