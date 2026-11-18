
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.authorization import enforce_write_access, get_optional_user, require_role
from app.core.database import get_db
from app.models.auth import User, UserRole
from app.models.claim import Claim
from app.models.evidence import Citation, ClaimEvidence, Source, SourceVerificationStatus
from app.core.clock import utcnow
from app.schemas.evidence import (
    CitationCreate,
    CitationRead,
    ClaimEvidenceSummary,
    EvidenceItemRead,
    EvidenceLinkCreate,
    EvidenceLinkRead,
    SourceCreate,
    SourceRead,
    SourceTypeReview,
)
from app.services.claim_confidence import AUTOMATED_SOURCE_CHECK, AUTOMATED_SOURCE_CHECK_DETAIL, assess_claim, source_record
from app.services.evidence_scoring import score_source, summarize_evidence

router = APIRouter(tags=["evidence"])


@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    enforce_write_access(user)
    quality_score, rationale = score_source(payload.source_type, payload.publisher, payload.author)
    source = Source(
        title=payload.title,
        url=str(payload.url) if payload.url is not None else None,
        document_reference=payload.document_reference,
        publisher=payload.publisher,
        author=payload.author,
        publication_date=payload.publication_date,
        source_type=payload.source_type,
        source_type_reviewed=False,
        verification_status=SourceVerificationStatus.unverified,
        quality_score=quality_score,
        quality_rationale=rationale,
    )
    db.add(source)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A source with this URL already exists") from exc
    db.refresh(source)
    return source


@router.get("/sources/{source_id}", response_model=SourceRead)
def get_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.post("/citations", response_model=CitationRead, status_code=status.HTTP_201_CREATED)
def create_citation(payload: CitationCreate, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    enforce_write_access(user)
    if not db.get(Source, payload.source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    citation = Citation(**payload.model_dump())
    db.add(citation)
    db.commit()
    db.refresh(citation)
    return citation


@router.post("/claims/{claim_id}/evidence", response_model=EvidenceLinkRead, status_code=status.HTTP_201_CREATED)
def link_evidence(claim_id: int, payload: EvidenceLinkCreate, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    enforce_write_access(user)
    if not db.get(Claim, claim_id):
        raise HTTPException(status_code=404, detail="Claim not found")
    if not db.get(Citation, payload.citation_id):
        raise HTTPException(status_code=404, detail="Citation not found")

    link = ClaimEvidence(claim_id=claim_id, **payload.model_dump())
    db.add(link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This citation is already linked to the claim") from exc
    db.refresh(link)
    return link


@router.get("/claims/{claim_id}/evidence-summary", response_model=ClaimEvidenceSummary)
def get_evidence_summary(claim_id: int, db: Session = Depends(get_db)):
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    links = (
        db.query(ClaimEvidence)
        .options(joinedload(ClaimEvidence.citation).joinedload(Citation.source))
        .filter(ClaimEvidence.claim_id == claim_id)
        .all()
    )
    summary = summarize_evidence(links)
    confidence = assess_claim(db, claim_id)
    db.commit()
    return ClaimEvidenceSummary(
        claim_id=claim_id,
        items=[EvidenceItemRead(**item.__dict__) for item in summary.items],
        strongest_effective_tier=summary.strongest_effective_tier,
        independent_source_count=summary.independent_source_count,
        citation_count=summary.citation_count,
        citation_requirement_met=(not claim.citation_required) or summary.citation_count > 0,
        confidence={"claim_id": claim_id, **confidence},
    )


@router.get("/sources/{source_id}/record")
def get_source_record(source_id: int, db: Session = Depends(get_db)):
    if not db.get(Source, source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    record = source_record(db, source_id)
    return {
        "source_id": source_id,
        "corrected": record.corrected,
        "retracted": record.retracted,
        "found_false": record.found_false,
        "confirmed": record.confirmed,
        "track_factor": record.track_factor,
        "automated_source_check": AUTOMATED_SOURCE_CHECK,
        "automated_source_check_detail": AUTOMATED_SOURCE_CHECK_DETAIL,
    }


@router.post("/sources/{source_id}/source-type-review", response_model=SourceRead)
def review_source_type(
    source_id: int,
    payload: SourceTypeReview,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.source_type_reviewed = True
    source.source_type_reviewed_by_user_id = user.id
    source.source_type_reviewed_at = utcnow()
    source.quality_score, source.quality_rationale = score_source(
        source.source_type,
        source.publisher,
        source.author,
        source_type_reviewed=True,
    )
    source.quality_rationale = f"{source.quality_rationale} Review note: {payload.note.strip()}"
    db.commit()
    db.refresh(source)
    return source
