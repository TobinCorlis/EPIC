from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.authorization import enforce_write_access, get_optional_user, require_authenticated
from app.core.database import get_db
from app.models.auth import User
from app.models.claim import Claim
from app.models.evidence import Citation, ClaimEvidence, Source
from app.core.clock import utcnow
from app.models.factcheck import SourceCheck, VerificationJob
from app.schemas.evidence import SourceRead
from app.schemas.factcheck import SourceCheckRead, SourceUpdate, VerificationJobRead
from app.services.evidence_scoring import score_source
from app.services.factcheck.http import get_transport
from app.services.factcheck.text import extract_doi
from app.services.factcheck.runner import enqueue_verification, run_claim_checks, run_source_checks

router = APIRouter(tags=["factcheck"])

FLAGGED = {
    "low_confidence",
    "mismatch",
    "quote_not_found",
    "text_not_accessible",
    "possible_counterevidence",
    "not_found",
    "not_findable",
    "retracted",
    "expression_of_concern",
    "corrected",
    "check_failed",
}


def _enrich(db: Session, rows: list[SourceCheck]) -> list[SourceCheckRead]:
    source_ids = {row.source_id for row in rows if row.source_id}
    sources = {
        source.id: source
        for source in db.query(Source).filter(Source.id.in_(source_ids or [0])).all()
    }
    enriched = []
    for row in rows:
        payload = SourceCheckRead.model_validate(row).model_dump()
        source = sources.get(row.source_id)
        if source is not None:
            payload["source_title"] = source.title
            payload["source_locator"] = extract_doi(source.url, source.document_reference) or source.url or source.document_reference
        if payload["claim_id"] is None and row.citation_id is not None:
            link = db.query(ClaimEvidence.claim_id).filter(ClaimEvidence.citation_id == row.citation_id).first()
            if link is not None:
                payload["claim_id"] = link[0]
        enriched.append(SourceCheckRead(**payload))
    return enriched


def _checks_for_source(db: Session, source_id: int) -> list[SourceCheck]:
    return db.query(SourceCheck).filter(SourceCheck.source_id == source_id).order_by(SourceCheck.id).all()


@router.patch("/sources/{source_id}", response_model=SourceRead)
def update_source(
    source_id: int,
    payload: SourceUpdate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    enforce_write_access(user)
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No source fields were changed")
    for name, value in changes.items():
        setattr(source, name, value)
    if source.url is None and not (source.document_reference or "").strip():
        raise HTTPException(status_code=422, detail="A source requires a URL or a document reference")
    source.quality_score, source.quality_rationale = score_source(
        source.source_type,
        source.publisher,
        source.author,
        source_type_reviewed=source.source_type_reviewed,
    )
    enqueue_verification(db, "source", source.id, user.id if user else None)
    db.commit()
    db.refresh(source)
    return source


@router.get("/sources/{source_id}/checks", response_model=list[SourceCheckRead])
def list_source_checks(source_id: int, db: Session = Depends(get_db)):
    if db.get(Source, source_id) is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return _enrich(db, _checks_for_source(db, source_id))


@router.post("/sources/{source_id}/checks", response_model=list[SourceCheckRead])
def rerun_source_checks(
    source_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    if db.get(Source, source_id) is None:
        raise HTTPException(status_code=404, detail="Source not found")
    job = VerificationJob(
        subject_type="source",
        subject_id=source_id,
        status="running",
        requested_by_user_id=user.id,
        attempt_count=1,
        claimed_at=utcnow(),
        worker_id="api",
    )
    db.add(job)
    db.commit()
    try:
        run_source_checks(db, source_id, transport=get_transport(), actor_id=user.id)
        job = db.get(VerificationJob, job.id)
        if job is not None:
            job.status = "completed"
            job.completed_at = utcnow()
            job.error_message = None
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(VerificationJob, job.id)
        if job is not None:
            job.status = "check_failed"
            job.error_message = str(exc)[:2000]
            db.commit()
        raise
    return _enrich(db, _checks_for_source(db, source_id))


@router.get("/claims/{claim_id}/checks", response_model=list[SourceCheckRead])
def list_claim_checks(claim_id: int, db: Session = Depends(get_db)):
    if db.get(Claim, claim_id) is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    source_ids = [
        row[0]
        for row in (
            db.query(Citation.source_id)
            .join(ClaimEvidence, ClaimEvidence.citation_id == Citation.id)
            .filter(ClaimEvidence.claim_id == claim_id)
            .all()
        )
    ]
    filters = [SourceCheck.claim_id == claim_id]
    if source_ids:
        filters.append(SourceCheck.source_id.in_(source_ids))
    rows = db.query(SourceCheck).filter(or_(*filters)).order_by(SourceCheck.id).all()
    return _enrich(db, rows)


@router.post("/claims/{claim_id}/checks", response_model=list[SourceCheckRead])
def rerun_claim_checks(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    if db.get(Claim, claim_id) is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    job = VerificationJob(
        subject_type="claim",
        subject_id=claim_id,
        status="running",
        requested_by_user_id=user.id,
        attempt_count=1,
        claimed_at=utcnow(),
        worker_id="api",
    )
    db.add(job)
    db.commit()
    try:
        run_claim_checks(db, claim_id, transport=get_transport(), actor_id=user.id)
        job = db.get(VerificationJob, job.id)
        if job is not None:
            job.status = "completed"
            job.completed_at = utcnow()
            job.error_message = None
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(VerificationJob, job.id)
        if job is not None:
            job.status = "check_failed"
            job.error_message = str(exc)[:2000]
            db.commit()
        raise
    return list_claim_checks(claim_id, db)


@router.get("/factcheck/queue", response_model=list[SourceCheckRead])
def factcheck_queue(db: Session = Depends(get_db), _: User = Depends(require_authenticated)):
    flagged = (
        db.query(SourceCheck)
        .filter(SourceCheck.result.in_(FLAGGED), SourceCheck.superseded.is_(False))
        .order_by(SourceCheck.id.desc())
        .limit(100)
        .all()
    )
    consensus = (
        db.query(SourceCheck)
        .filter(
            SourceCheck.result == "possible_corroboration",
            SourceCheck.superseded.is_(False),
            SourceCheck.detail.contains("Systematic review"),
        )
        .order_by(SourceCheck.id.desc())
        .limit(50)
        .all()
    )
    rows = {row.id: row for row in flagged}
    for row in consensus:
        rows.setdefault(row.id, row)
    ordered = [rows[key] for key in sorted(rows, reverse=True)]
    return _enrich(db, ordered)


@router.get("/factcheck/jobs", response_model=list[VerificationJobRead])
def factcheck_jobs(db: Session = Depends(get_db), _: User = Depends(require_authenticated)):
    return db.query(VerificationJob).order_by(VerificationJob.id.desc()).limit(50).all()
