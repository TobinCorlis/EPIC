from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.authorization import enforce_write_access, get_optional_user
from app.core.database import get_db
from app.models.auth import User
from app.models.claim import Claim
from app.models.evidence import Citation, ClaimEvidence, Source
from app.schemas.evidence import (
    CitationCreate,
    CitationRead,
    ClaimEvidenceSummary,
    EvidenceLinkCreate,
    EvidenceLinkRead,
    SourceCreate,
    SourceRead,
)
from app.services.evidence_scoring import score_source, summarize_evidence

router = APIRouter(tags=["evidence"])


@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    enforce_write_access(user)
    quality_score, rationale = score_source(payload.source_type, payload.publisher, payload.author)
    source_data = payload.model_dump(exclude={"url"})
    source = Source(
        **source_data,
        url=str(payload.url),
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
    return ClaimEvidenceSummary(
        claim_id=claim_id,
        supports_score=summary.supports_score,
        contradicts_score=summary.contradicts_score,
        contextual_score=summary.contextual_score,
        net_evidence_score=summary.net_evidence_score,
        citation_count=summary.citation_count,
        citation_requirement_met=(not claim.citation_required) or summary.citation_count > 0,
    )
