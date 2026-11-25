"""Backfills for fact-check rows recorded before later rules."""
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

MISREAD_RETRACTION_REASON = "notice misread as retracted paper"
_PLACEHOLDER_TITLE = re.compile(r"^Retraction notice\s+(10\.\S+)$", re.I)
_NOTICE_TITLE = re.compile(r"^\s*retraction(?:\s+note|\s+notice)?\b", re.I)


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


def title_from_detail(detail: str | None) -> str:
    marker = "Title: "
    if marker not in (detail or ""):
        return ""
    return (detail or "").rsplit(marker, 1)[1].strip()


def supersede_stale_leads(session: Session) -> None:
    """Mark off-topic and duplicate related-work rows superseded. Do not delete them."""
    from app.core.config import settings
    from app.models.claim import Claim
    from app.models.factcheck import SourceCheck
    from app.services.factcheck.checkers import topic_overlap

    bodies = {row.id: row.body for row in session.query(Claim.id, Claim.body).all()}
    leads = (
        session.query(SourceCheck)
        .filter(SourceCheck.checker_name == "related_work")
        .order_by(SourceCheck.id)
        .all()
    )
    for lead in leads:
        overlap = topic_overlap(bodies.get(lead.claim_id) or "", title_from_detail(lead.detail))
        if overlap < settings.factcheck_lead_min_overlap:
            lead.superseded = True
    groups: dict[tuple, list] = {}
    for lead in leads:
        if lead.superseded:
            continue
        key = (lead.claim_id, lead.response_id or lead.evidence_url or f"row:{lead.id}")
        groups.setdefault(key, []).append(lead)
    for group in groups.values():
        group.sort(key=lambda row: row.id)
        for older in group[:-1]:
            older.superseded = True
    session.flush()


def supersede_older_checks(session: Session) -> None:
    """Keep the latest check of each type and fill quote rows with their claim."""
    from app.models.evidence import ClaimEvidence
    from app.models.factcheck import SourceCheck

    quotes = (
        session.query(SourceCheck)
        .filter(
            SourceCheck.checker_name == "quote",
            SourceCheck.claim_id.is_(None),
            SourceCheck.citation_id.is_not(None),
        )
        .all()
    )
    for quote in quotes:
        link = (
            session.query(ClaimEvidence.claim_id)
            .filter(ClaimEvidence.citation_id == quote.citation_id)
            .order_by(ClaimEvidence.id)
            .first()
        )
        if link is not None:
            quote.claim_id = link[0]
    session.flush()
    current = (
        session.query(SourceCheck)
        .filter(SourceCheck.superseded.is_(False))
        .order_by(SourceCheck.id)
        .all()
    )
    groups: dict[tuple, list] = {}
    for row in current:
        if row.checker_name == "related_work":
            key = (row.source_id, row.claim_id, row.citation_id, row.checker_name, row.response_id or row.evidence_url)
        else:
            key = (row.source_id, row.claim_id, row.citation_id, row.checker_name)
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        group.sort(key=lambda item: item.id)
        for older in group[:-1]:
            older.superseded = True
    session.flush()


def _source_doi(source) -> str | None:
    from app.services.factcheck.text import extract_doi

    return extract_doi(source.url, source.document_reference)


def retitle_placeholder_notices(session: Session, titles_by_doi: dict | None = None) -> int:
    """Replace 'Retraction notice <DOI>' with the Crossref title. Returns how many changed."""
    from app.models.evidence import Source
    from app.services.factcheck.checkers import crossref_record
    from app.services.factcheck.http import HttpxTransport

    changed = 0
    transport = None
    for source in session.query(Source).all():
        match = _PLACEHOLDER_TITLE.match(source.title or "")
        if match is None:
            continue
        doi = match.group(1)
        record = None
        if titles_by_doi is not None:
            record = titles_by_doi.get(doi) or titles_by_doi.get(doi.lower())
        else:
            if transport is None:
                transport = HttpxTransport()
            try:
                record = crossref_record(transport, doi)
            except Exception:
                record = None
        if not record or not record.get("title"):
            continue
        source.title = record["title"][:500]
        if record.get("author"):
            source.author = str(record["author"])[:300]
        if record.get("journal"):
            source.publisher = record["journal"][:300]
        if record.get("year"):
            source.publication_date = datetime(int(record["year"]), 1, 1)
        changed += 1
    session.flush()
    return changed


def repair_misread_retraction_notices(session: Session, titles_by_doi: dict | None = None) -> int:
    """Reverse invalidations that treated a retraction notice as the retracted paper.

    Audit rows stay. The wrong check is superseded. The reversal reason is
    'notice misread as retracted paper' and the actor is system:factcheck.
    """
    from app.models.evidence import Source
    from app.models.factcheck import SourceCheck
    from app.models.library import UpstreamInvalidation
    from app.services.factcheck.runner import system_factcheck_user
    from app.services.reference_library import reverse_upstream_invalidation

    retitle_placeholder_notices(session, titles_by_doi)
    reversed_count = 0
    for source in session.query(Source).all():
        if _NOTICE_TITLE.match(source.title or "") is None:
            continue
        checks = (
            session.query(SourceCheck)
            .filter(
                SourceCheck.source_id == source.id,
                SourceCheck.checker_name == "retraction",
                SourceCheck.result == "retracted",
                SourceCheck.superseded.is_(False),
            )
            .all()
        )
        for check in checks:
            check.superseded = True
        invalidations = (
            session.query(UpstreamInvalidation)
            .filter(
                UpstreamInvalidation.subject_type == "source",
                UpstreamInvalidation.subject_id == source.id,
                UpstreamInvalidation.kind == "retraction",
                UpstreamInvalidation.reversed_reason.is_(None),
            )
            .all()
        )
        if not invalidations:
            continue
        actor = system_factcheck_user(session)
        for invalidation in invalidations:
            reverse_upstream_invalidation(session, invalidation, actor, MISREAD_RETRACTION_REASON)
            reversed_count += 1
    session.flush()
    return reversed_count
