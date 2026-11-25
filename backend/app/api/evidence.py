
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
    SourceRecordReview,
    SourceTypeReview,
)
from app.services.claim_confidence import assess_claim, source_record
from app.services.factcheck.runner import enqueue_verification, kickoff
from app.services.factcheck.status import describe_source
from app.services.evidence_scoring import score_source, summarize_evidence
from app.services.scope_review import review_claim_scope

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
        scope_population=payload.scope_population,
        scope_timeframe=payload.scope_timeframe,
        scope_geography=payload.scope_geography,
        scope_metric=payload.scope_metric,
        scope_study_type=payload.scope_study_type,
        scope_sample_size=payload.scope_sample_size,
        source_type_reviewed=False,
        verification_status=SourceVerificationStatus.unverified,
        quality_score=quality_score,
        quality_rationale=rationale,
    )
    db.add(source)
    try:
        db.flush()
        job = enqueue_verification(db, "source", source.id, user.id if user else None)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A source with this URL already exists") from exc
    db.refresh(source)
    kickoff(job.id)
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
    db.flush()
    job = enqueue_verification(db, "source", citation.source_id, user.id if user else None)
    db.commit()
    db.refresh(citation)
    kickoff(job.id)
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
    review_claim_scope(db, db.get(Claim, claim_id))
    try:
        db.flush()
        job = enqueue_verification(db, "claim", claim_id, user.id if user else None)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This citation is already linked to the claim") from exc
    db.refresh(link)
    kickoff(job.id)
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
    flags = review_claim_scope(db, claim)
    db.commit()
    links_by_id = {link.id: link for link in links}
    items = []
    for item in summary.items:
        payload = dict(item.__dict__)
        link = links_by_id.get(item.claim_evidence_id)
        if link is not None and link.citation is not None and link.citation.source is not None:
            source = link.citation.source
            payload["source_id"] = source.id
            payload["source_title"] = source.title
            payload["scope_population"] = link.scope_population or source.scope_population
            payload["scope_timeframe"] = link.scope_timeframe or source.scope_timeframe
            payload["scope_geography"] = link.scope_geography or source.scope_geography
            payload["scope_metric"] = link.scope_metric or source.scope_metric
            payload["scope_study_type"] = link.scope_study_type or source.scope_study_type
            payload["scope_sample_size"] = link.scope_sample_size if link.scope_sample_size is not None else source.scope_sample_size
        items.append(EvidenceItemRead(**payload))
    return ClaimEvidenceSummary(
        claim_id=claim_id,
        items=items,
        strongest_effective_tier=summary.strongest_effective_tier,
        independent_source_count=summary.independent_source_count,
        citation_count=summary.citation_count,
        citation_requirement_met=(not claim.citation_required) or summary.citation_count > 0,
        confidence={"claim_id": claim_id, **confidence},
        scope_flags=flags,
    )


@router.get("/sources/{source_id}/record")
def get_source_record(source_id: int, db: Session = Depends(get_db)):
    if not db.get(Source, source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    record = source_record(db, source_id)
    status_name, detail = describe_source(db, source_id)
    return {
        "source_id": source_id,
        "corrected": record.corrected,
        "retracted": record.retracted,
        "found_false": record.found_false,
        "confirmed": record.confirmed,
        "track_factor": record.track_factor,
        "automated_source_check": status_name,
        "automated_source_check_detail": detail,
    }


@router.post("/sources/{source_id}/record-review", response_model=SourceRead)
def review_source_record(
    source_id: int,
    payload: SourceRecordReview,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    """Record a human check that a cited source was found, or that no record exists.

    This does not fetch the source and does not mark it verified.
    """
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.record_status = payload.status
    source.record_note = payload.note.strip()
    source.record_checked_by_user_id = user.id
    source.record_checked_at = utcnow()
    db.commit()
    db.refresh(source)
    return source


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
