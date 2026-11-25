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
