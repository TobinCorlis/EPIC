"""Backfills for fact-check rows recorded before later rules."""
from sqlalchemy import text
from sqlalchemy.orm import Session


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
