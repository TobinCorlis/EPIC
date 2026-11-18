from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import require_authenticated
from app.core.database import get_db
from app.models.auth import User
from app.models.claim import Claim
from app.models.correction import ClaimCorrection
from app.models.knowledge import KnowledgeClaim
from app.schemas.claim import ClaimRead, CorrectionCreate
from app.schemas.knowledge import KnowledgeClaimRead
from app.services.knowledge_matching import fingerprint_claim, normalize_claim

router = APIRouter(tags=["corrections"])


def _apply_correction(target, payload: CorrectionCreate, user: User, *, knowledge: bool) -> ClaimCorrection:
    corrected = payload.corrected_body.strip()
    if corrected == target.body:
        raise HTTPException(status_code=422, detail="The corrected text is the same as the current text")
    correction = ClaimCorrection(
        claim_id=None if knowledge else target.id,
        knowledge_claim_id=target.id if knowledge else None,
        original_body=target.body,
        corrected_body=corrected,
        reason=payload.reason.strip(),
        author_user_id=user.id,
    )
    target.body = corrected
    if payload.uncertainty is not None:
        target.uncertainty = payload.uncertainty.strip() or None
    if knowledge:
        target.normalized_body = normalize_claim(corrected)
        target.fingerprint = fingerprint_claim(corrected)
    return correction


@router.post("/claims/{claim_id}/corrections", response_model=ClaimRead)
def correct_debate_claim(
    claim_id: int,
    payload: CorrectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    db.add(_apply_correction(claim, payload, user, knowledge=False))
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/knowledge/claims/{claim_id}/corrections", response_model=KnowledgeClaimRead)
def correct_knowledge_claim(
    claim_id: int,
    payload: CorrectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    claim = db.get(KnowledgeClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Knowledge claim not found")
    db.add(_apply_correction(claim, payload, user, knowledge=True))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The corrected text matches an existing claim in this dossier",
        ) from exc
    db.refresh(claim)
    return claim
