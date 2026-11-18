from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.authorization import enforce_write_access, get_optional_user
from app.core.database import get_db
from app.models.auth import User, UserRole
from app.models.claim import Claim
from app.models.debate import Debate
from app.schemas.claim import ClaimCreate, ClaimRead
from app.schemas.debate import DebateCreate, DebateRead
from app.services.moderation import evaluate_topic_alignment

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
    db.commit()
    db.refresh(debate)
    return debate


@router.get("/{debate_id}", response_model=DebateRead)
def get_debate(debate_id: int, db: Session = Depends(get_db)):
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
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
        citation_required=payload.claim_type.value != "opinion",
        on_topic=result.on_topic,
        moderation_note=result.note,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


@router.get("/{debate_id}/claims", response_model=list[ClaimRead])
def list_claims(debate_id: int, db: Session = Depends(get_db)):
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    return db.query(Claim).filter(Claim.debate_id == debate_id).order_by(Claim.id).all()
