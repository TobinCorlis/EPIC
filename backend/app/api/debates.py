from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.authorization import enforce_write_access, get_optional_user
from app.core.database import get_db
from app.models.auth import User, UserRole
from app.models.argument import ArgumentNode
from app.models.claim import Claim
from app.models.debate import Debate
from app.models.knowledge import KnowledgeClaim
from app.models.status_history import StatusHistory
from app.schemas.claim import ClaimCreate, ClaimRead
from app.schemas.status_history import StatusHistoryRead
from app.schemas.debate import DebateCreate, DebateRead
from app.services.moderation import evaluate_topic_alignment
from app.services.reference_library import annotate_debate, annotate_point, consider_debate, consider_text
from app.services.referee import evidence_flags
from app.api.library import enqueue_after

router = APIRouter(prefix="/debates", tags=["debates"])


@router.post("", response_model=DebateRead, status_code=status.HTTP_201_CREATED)
def create_debate(
    payload: DebateCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    enforce_write_access(user)
    debate = Debate(owner_user_id=user.id if user else None, **payload.model_dump())
    db.add(debate)
    db.flush()
    consider_debate(db, debate)
    db.flush()
    annotate_debate(db, debate)
    db.commit()
    db.refresh(debate)
    annotate_debate(db, debate)
    return debate


@router.get("/{debate_id}/evidence-checks")
def debate_evidence_checks(debate_id: int, db: Session = Depends(get_db)):
    """Flags that can be read from recorded links. This does not decide who is right."""
    if not db.get(Debate, debate_id):
        raise HTTPException(status_code=404, detail="Debate not found")
    return {"debate_id": debate_id, "flags": evidence_flags(db, debate_id)}


@router.get("/{debate_id}", response_model=DebateRead)
def get_debate(debate_id: int, db: Session = Depends(get_db)):
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    annotate_debate(db, debate)
    return debate


@router.post("/{debate_id}/claims", response_model=ClaimRead, status_code=status.HTTP_201_CREATED)
def add_claim(
    debate_id: int,
    payload: ClaimCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    enforce_write_access(user)
    if user and debate.owner_user_id and user.id != debate.owner_user_id and user.role not in {UserRole.moderator, UserRole.administrator}:
        raise HTTPException(status_code=403, detail="Only the debate owner or platform staff may add claims")

    result = evaluate_topic_alignment(debate.fixed_question, payload.body)
    claim = Claim(
        debate_id=debate_id,
        body=payload.body,
        claim_type=payload.claim_type,
        claim_role=payload.claim_role,
        citation_required=payload.claim_type.value != "opinion",
        on_topic=True,
        needs_review=result.needs_review,
        needs_review_reasons='["moderation"]' if result.needs_review else "[]",
        moderation_note=result.note,
        uncertainty=(payload.uncertainty or "").strip() or None,
        scope_population=payload.scope_population,
        scope_timeframe=payload.scope_timeframe,
        scope_geography=payload.scope_geography,
        scope_metric=payload.scope_metric,
        answerability=payload.answerability,
        answerability_reason=(payload.answerability_reason or "").strip() or None,
    )
    db.add(claim)
    db.flush()
    job_ids = consider_text(db, debate, claim.body, claim_id=claim.id)
    db.flush()
    annotate_point(db, claim, claim_id=claim.id)
    db.commit()
    enqueue_after(job_ids)
    db.refresh(claim)
    annotate_point(db, claim, claim_id=claim.id)
    return claim


def _notes_for_claim(db: Session, claim_id: int) -> list[StatusHistoryRead]:
    argument_ids = [
        row[0]
        for row in db.query(ArgumentNode.id).filter(ArgumentNode.claim_id == claim_id).all()
    ]
    knowledge_ids = [
        row[0]
        for row in db.query(KnowledgeClaim.id).filter(KnowledgeClaim.originating_claim_id == claim_id).all()
    ]
    filters = []
    if argument_ids:
        filters.append((StatusHistory.subject_type == "argument_node") & (StatusHistory.subject_id.in_(argument_ids)))
    if knowledge_ids:
        filters.append((StatusHistory.subject_type == "knowledge_claim") & (StatusHistory.subject_id.in_(knowledge_ids)))
    if not filters:
        return []
    from sqlalchemy import or_

    rows = (
        db.query(StatusHistory)
        .filter(or_(*filters))
        .order_by(StatusHistory.id)
        .all()
    )
    return [StatusHistoryRead.model_validate(row) for row in rows]


@router.get("/{debate_id}/claims", response_model=list[ClaimRead])
def list_claims(debate_id: int, db: Session = Depends(get_db)):
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    claims = db.query(Claim).filter(Claim.debate_id == debate_id).order_by(Claim.id).all()
    result = []
    for claim in claims:
        annotate_point(db, claim, claim_id=claim.id)
        from app.models.library import ReevaluationRequest

        claim.reevaluation_pending = (
            db.query(ReevaluationRequest)
            .filter(ReevaluationRequest.claim_id == claim.id, ReevaluationRequest.status == "open")
            .first()
            is not None
        )
        payload = ClaimRead.model_validate(claim)
        payload.status_notes = _notes_for_claim(db, claim.id)
        result.append(payload)
    return result
