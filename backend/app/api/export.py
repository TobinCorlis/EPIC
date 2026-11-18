from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models.argument import ModeratorRuling, Participant
from app.models.claim import Claim
from app.models.debate import Debate
from app.models.evidence import Citation, ClaimEvidence

router = APIRouter(prefix="/debates", tags=["exports"])


def _debate_or_404(db: Session, debate_id: int) -> Debate:
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    return debate


@router.get("/{debate_id}/export")
def export_debate_json(debate_id: int, db: Session = Depends(get_db)):
    debate = _debate_or_404(db, debate_id)
    claims = db.query(Claim).filter(Claim.debate_id == debate_id).order_by(Claim.id).all()
    participants = db.query(Participant).filter(Participant.debate_id == debate_id).order_by(Participant.id).all()
    rulings = db.query(ModeratorRuling).filter(ModeratorRuling.debate_id == debate_id).order_by(ModeratorRuling.id).all()
    evidence = (
        db.query(ClaimEvidence)
        .options(joinedload(ClaimEvidence.citation).joinedload(Citation.source))
        .join(Claim, Claim.id == ClaimEvidence.claim_id)
        .filter(Claim.debate_id == debate_id)
        .order_by(ClaimEvidence.id)
        .all()
    )
    return {
        "debate": {"id": debate.id, "title": debate.title, "fixed_question": debate.fixed_question, "description": debate.description, "status": debate.status.value if hasattr(debate.status, "value") else str(debate.status)},
        "participants": [{"id": p.id, "name": p.display_name, "role": p.role.value, "side": p.side.value} for p in participants],
        "claims": [{"id": c.id, "body": c.body, "claim_type": c.claim_type.value, "citation_required": c.citation_required, "on_topic": c.on_topic, "moderation_note": c.moderation_note, "uncertainty": c.uncertainty, "corrections": [{"id": item.id, "original_body": item.original_body, "corrected_body": item.corrected_body, "reason": item.reason, "author_user_id": item.author_user_id, "created_at": item.created_at.isoformat()} for item in c.corrections]} for c in claims],
        "evidence": [{"id": e.id, "claim_id": e.claim_id, "stance": e.stance.value, "claim_supported": e.claim_supported, "relevance_score": e.relevance_score, "note": e.note, "citation": {"id": e.citation.id, "locator": e.citation.locator, "excerpt": e.citation.excerpt, "source": {"id": e.citation.source.id, "title": e.citation.source.title, "url": e.citation.source.url, "document_reference": e.citation.source.document_reference, "publisher": e.citation.source.publisher, "author": e.citation.source.author, "source_type": e.citation.source.source_type.value, "source_type_reviewed": e.citation.source.source_type_reviewed, "verification_status": e.citation.source.verification_status.value, "archive_url": e.citation.source.archive_url, "archived_at": e.citation.source.archived_at.isoformat() if e.citation.source.archived_at else None, "quality_score": e.citation.source.quality_score}}} for e in evidence],
        "rulings": [{"id": r.id, "outcome": r.outcome.value, "rationale": r.rationale, "rule_reference": r.rule_reference, "created_at": r.created_at.isoformat()} for r in rulings],
    }


@router.get("/{debate_id}/export.md", response_class=PlainTextResponse)
def export_debate_markdown(debate_id: int, db: Session = Depends(get_db)):
    data = export_debate_json(debate_id, db)
    d = data["debate"]
    lines = [f"# {d['title']}", "", f"**Fixed question:** {d['fixed_question']}", ""]
    if d.get("description"):
        lines += [d["description"], ""]
    lines += ["## Claims", ""]
    if not data["claims"]:
        lines.append("No claims recorded.")
    for claim in data["claims"]:
        lines += [f"### Claim {claim['id']}", claim["body"], f"- Type: {claim['claim_type']}", f"- On topic: {'Yes' if claim['on_topic'] else 'No'}"]
        if claim.get("uncertainty"):
            lines.append(f"- Uncertainty: {claim['uncertainty']}")
        for correction in claim.get("corrections") or []:
            lines.append(
                f"- Correction by user {correction['author_user_id']} at {correction['created_at']}: "
                f"'{correction['original_body']}' corrected to '{correction['corrected_body']}'. "
                f"Reason: {correction['reason']}"
            )
        linked = [e for e in data["evidence"] if e["claim_id"] == claim["id"]]
        if linked:
            lines.append("- Evidence:")
            for e in linked:
                src = e["citation"]["source"]
                locator = f" ({e['citation']['locator']})" if e["citation"]["locator"] else ""
                if src.get("url"):
                    located = f"[{src['title']}]({src['url']})"
                else:
                    located = f"{src['title']} — {src.get('document_reference')}"
                lines.append(
                    f"  - {e['stance']}: {located}{locator}. Claim supported: {e['claim_supported']}"
                )
        lines.append("")
    lines += ["## Moderator rulings", ""]
    if not data["rulings"]:
        lines.append("No moderator rulings recorded.")
    for ruling in data["rulings"]:
        lines += [f"- **{ruling['outcome']}** — {ruling['rationale']} ({ruling['rule_reference']})"]
    return "\n".join(lines) + "\n"
