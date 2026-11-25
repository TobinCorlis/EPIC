from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import require_enforced_staff, require_enforced_writer, require_role
from app.core.database import get_db
from app.models.auth import User, UserRole
from app.models.claim import Claim
from app.models.evidence import Source
from app.models.knowledge import (
    ClaimContradiction,
    ContradictionStatus,
    DossierSource,
    KnowledgeClaim,
    KnowledgeStatus,
    ResearchJob,
    ResearchJobEvent,
    ResearchJobStatus,
    TopicDossier,
)
from app.schemas.knowledge import (
    ClaimMatchRead,
    ContradictionRead,
    ContradictionUpdate,
    DossierCreate,
    DossierRead,
    DossierSourceCreate,
    DossierSourceRead,
    KnowledgeClaimCreate,
    KnowledgeClaimRead,
    ResearchJobCreate,
    ResearchJobEventRead,
    ResearchJobRead,
    ResearchJobUpdate,
)
from app.services.knowledge_matching import compare_claims, fingerprint_claim, normalize_claim
from app.services.research_worker import enqueue_research_job

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def require_dossier(db: Session, dossier_id: int) -> TopicDossier:
    dossier = db.get(TopicDossier, dossier_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Topic dossier not found")
    return dossier


@router.post("/dossiers", response_model=DossierRead, status_code=status.HTTP_201_CREATED)
def create_dossier(
    payload: DossierCreate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_enforced_writer),
):
    dossier = TopicDossier(**payload.model_dump())
    db.add(dossier)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A dossier with this title already exists") from exc
    db.refresh(dossier)
    return dossier


@router.get("/dossiers", response_model=list[DossierRead])
def list_dossiers(db: Session = Depends(get_db)):
    return db.query(TopicDossier).order_by(TopicDossier.updated_at.desc()).all()


@router.post("/dossiers/{dossier_id}/sources", response_model=DossierSourceRead, status_code=201)
def add_dossier_source(
    dossier_id: int,
    payload: DossierSourceCreate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_enforced_writer),
):
    require_dossier(db, dossier_id)
    if not db.get(Source, payload.source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    item = DossierSource(dossier_id=dossier_id, **payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Source is already in this dossier") from exc
    db.refresh(item)
    return item


@router.post("/dossiers/{dossier_id}/claims", response_model=KnowledgeClaimRead, status_code=201)
def add_knowledge_claim(
    dossier_id: int,
    payload: KnowledgeClaimCreate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_enforced_writer),
):
    require_dossier(db, dossier_id)
    if payload.originating_claim_id is not None and not db.get(Claim, payload.originating_claim_id):
        raise HTTPException(status_code=404, detail="Originating debate claim not found")

    normalized = normalize_claim(payload.body)
    item = KnowledgeClaim(
        dossier_id=dossier_id,
        body=payload.body,
        originating_claim_id=payload.originating_claim_id,
        normalized_body=normalized,
        fingerprint=fingerprint_claim(payload.body),
        status=KnowledgeStatus.unverified,
        confidence_score=0.0,
        uncertainty=(payload.uncertainty or "").strip() or None,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An identical normalized claim already exists") from exc

    others = db.query(KnowledgeClaim).filter(
        KnowledgeClaim.dossier_id == dossier_id,
        KnowledgeClaim.id != item.id,
    ).all()
    for other in others:
        result = compare_claims(item.body, other.body)
        if result.contradiction_candidate:
            left_id, right_id = sorted((item.id, other.id))
            db.add(ClaimContradiction(
                dossier_id=dossier_id,
                left_claim_id=left_id,
                right_claim_id=right_id,
                similarity_score=result.similarity,
                reason=result.reason,
            ))
    db.commit()
    db.refresh(item)
    return item


@router.get("/dossiers/{dossier_id}/claims", response_model=list[KnowledgeClaimRead])
def list_knowledge_claims(dossier_id: int, db: Session = Depends(get_db)):
    require_dossier(db, dossier_id)
    from app.models.library import ReevaluationRequest

    claims = db.query(KnowledgeClaim).filter(KnowledgeClaim.dossier_id == dossier_id).order_by(KnowledgeClaim.id).all()
    result = []
    for claim in claims:
        claim.reevaluation_pending = (
            db.query(ReevaluationRequest)
            .filter(ReevaluationRequest.knowledge_claim_id == claim.id, ReevaluationRequest.status == "open")
            .first()
            is not None
        )
        result.append(claim)
    return result


@router.post("/dossiers/{dossier_id}/match-claim", response_model=list[ClaimMatchRead])
def match_claim(
    dossier_id: int,
    payload: KnowledgeClaimCreate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_enforced_writer),
):
    require_dossier(db, dossier_id)
    matches = []
    for existing in db.query(KnowledgeClaim).filter(KnowledgeClaim.dossier_id == dossier_id).all():
        result = compare_claims(payload.body, existing.body)
        if result.similarity >= 0.2:
            matches.append(ClaimMatchRead(
                claim_id=existing.id,
                body=existing.body,
                similarity=result.similarity,
                duplicate=result.duplicate,
                contradiction_candidate=result.contradiction_candidate,
                reason=result.reason,
            ))
    return sorted(matches, key=lambda item: item.similarity, reverse=True)


@router.get("/dossiers/{dossier_id}/contradictions", response_model=list[ContradictionRead])
def list_contradictions(dossier_id: int, db: Session = Depends(get_db)):
    require_dossier(db, dossier_id)
    return db.query(ClaimContradiction).filter(ClaimContradiction.dossier_id == dossier_id).order_by(ClaimContradiction.id).all()


@router.patch("/contradictions/{contradiction_id}", response_model=ContradictionRead)
def update_contradiction(
    contradiction_id: int,
    payload: ContradictionUpdate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_enforced_staff),
):
    contradiction = db.get(ClaimContradiction, contradiction_id)
    if not contradiction:
        raise HTTPException(status_code=404, detail="Contradiction not found")
    contradiction.status = payload.status
    db.commit()
    db.refresh(contradiction)
    return contradiction


@router.post("/jobs", response_model=ResearchJobRead, status_code=201)
def create_research_job(
    payload: ResearchJobCreate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_enforced_writer),
):
    if payload.dossier_id is not None:
        require_dossier(db, payload.dossier_id)
    job = ResearchJob(**payload.model_dump())
    db.add(job)
    db.flush()
    db.add(ResearchJobEvent(job_id=job.id, progress_percent=0, step="Queued", message="Research job created"))
    db.commit()
    db.refresh(job)
    return job




@router.post("/jobs/auto", response_model=ResearchJobRead, status_code=201)
def create_auto_research_job(
    payload: ResearchJobCreate,
    db: Session = Depends(get_db),
    _: User | None = Depends(require_enforced_writer),
):
    if payload.dossier_id is not None:
        require_dossier(db, payload.dossier_id)
    job = ResearchJob(**payload.model_dump())
    db.add(job); db.flush()
    db.add(ResearchJobEvent(job_id=job.id, progress_percent=0, step="Queued", message="Background research queued"))
    db.commit(); db.refresh(job)
    enqueue_research_job(job.id)
    return job

@router.patch("/jobs/{job_id}", response_model=ResearchJobRead)
def update_research_job(
    job_id: int,
    payload: ResearchJobUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    job = db.get(ResearchJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")
    dishonest = (
        payload.result_summary is not None
        or payload.status == ResearchJobStatus.completed
        or payload.progress_percent == 100
        or (payload.status not in {None, ResearchJobStatus.cancelled})
    )
    if dishonest or payload.status != ResearchJobStatus.cancelled:
        raise HTTPException(
            status_code=409,
            detail=(
                "Automated research is not implemented. A job cannot be marked complete, "
                "advanced, or given a result summary. A moderator may cancel it."
            ),
        )
    job.status = ResearchJobStatus.cancelled
    job.current_step = "Cancelled"
    job.result_summary = None
    db.add(ResearchJobEvent(
        job_id=job.id,
        progress_percent=job.progress_percent,
        step=job.current_step,
        message=payload.message or f"Cancelled by user {user.id}",
    ))
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=ResearchJobRead)
def get_research_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ResearchJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")
    return job


@router.get("/jobs/{job_id}/events", response_model=list[ResearchJobEventRead])
def list_research_job_events(job_id: int, db: Session = Depends(get_db)):
    if not db.get(ResearchJob, job_id):
        raise HTTPException(status_code=404, detail="Research job not found")
    return db.query(ResearchJobEvent).filter(ResearchJobEvent.job_id == job_id).order_by(ResearchJobEvent.id).all()
