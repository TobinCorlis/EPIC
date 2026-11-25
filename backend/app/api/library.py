import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.authorization import require_authenticated, require_role
from app.core.database import get_db
from app.models.auth import User, UserRole
from app.models.claim import Claim
from app.models.evidence import Source
from app.models.knowledge import KnowledgeClaim
from app.models.verification import VerificationEvent
from app.models.library import (
    LibraryPoint,
    ReferenceEntry,
    ReferenceEntryClaim,
    ReferenceEntrySource,
    ReferenceEntryVerification,
    ReferenceEntryVersion,
    ReevaluationRequest,
)
from app.schemas.library import (
    InvalidationCreate,
    LibraryClaimBrief,
    LibraryEntryCreate,
    LibraryEntryRead,
    LibrarySourceBrief,
    LibraryVerificationBrief,
    LibraryVersionRead,
    InvalidationReverse,
    PointResolve,
    ReevaluationCreate,
    ReevaluationDecision,
    ReevaluationRead,
)
from app.services.reference_library import (
    LibraryError,
    create_entry,
    decide_request,
    latest_version,
    open_request,
    record_upstream_invalidation,
    reverse_upstream_invalidation,
    resolve_point,
    search_entries,
)
from app.services.research_worker import enqueue_research_job

router = APIRouter(prefix="/library", tags=["library"])


def _request_read(item: ReevaluationRequest, names: dict[int, str]) -> ReevaluationRead:
    row = ReevaluationRead.model_validate(item)
    row.requested_by_display_name = names.get(item.requested_by_user_id)
    return row


def _guard(action):
    try:
        return action()
    except LibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _version_read(db: Session, version: ReferenceEntryVersion) -> LibraryVersionRead:
    from app.services.reference_library import relabel_version_confidence

    relabel_version_confidence(db, version)
    parsed = None
    if version.confidence_json:
        try:
            loaded = json.loads(version.confidence_json)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            parsed = loaded
    row = LibraryVersionRead.model_validate(version)
    row.confidence = parsed
    return row


def _read_entry(db: Session, entry: ReferenceEntry) -> LibraryEntryRead:
    from app.services.reference_library import ensure_entry_status

    ensure_entry_status(db, entry)
    db.commit()
    versions = (
        db.query(ReferenceEntryVersion)
        .filter(ReferenceEntryVersion.entry_id == entry.id)
        .order_by(ReferenceEntryVersion.version_number)
        .all()
    )
    current = None if entry.stale else latest_version(db, entry.id)
    claim_ids = [
        row[0]
        for row in db.query(ReferenceEntryClaim.claim_id).filter(ReferenceEntryClaim.entry_id == entry.id).all()
    ]
    source_ids = [
        row[0]
        for row in db.query(ReferenceEntrySource.source_id).filter(ReferenceEntrySource.entry_id == entry.id).all()
    ]
    event_ids = [
        row[0]
        for row in db.query(ReferenceEntryVerification.verification_event_id)
        .filter(ReferenceEntryVerification.entry_id == entry.id)
        .all()
    ]
    claims = db.query(Claim).filter(Claim.id.in_(claim_ids)).all() if claim_ids else []
    sources = db.query(Source).filter(Source.id.in_(source_ids)).all() if source_ids else []
    events = db.query(VerificationEvent).filter(VerificationEvent.id.in_(event_ids)).all() if event_ids else []
    label = None
    if entry.reevaluation_pending:
        label = "re-evaluation pending"
    elif entry.stale:
        label = "stale"
    elif entry.needs_review:
        label = "needs review"
    requests = (
        db.query(ReevaluationRequest)
        .filter(ReevaluationRequest.entry_id == entry.id)
        .order_by(ReevaluationRequest.id)
        .all()
    )
    user_ids = {item.requested_by_user_id for item in requests}
    names = {}
    if user_ids:
        names = {user.id: user.display_name for user in db.query(User).filter(User.id.in_(user_ids)).all()}
    return LibraryEntryRead(
        id=entry.id,
        question=entry.question,
        question_population=entry.question_population,
        question_timeframe=entry.question_timeframe,
        question_geography=entry.question_geography,
        question_metric=entry.question_metric,
        stale=entry.stale,
        reevaluation_pending=entry.reevaluation_pending,
        needs_review=entry.needs_review,
        status_label=label,
        current_version=_version_read(db, current) if current else None,
        versions=[_version_read(db, version) for version in versions],
        supporting_claim_ids=claim_ids,
        supporting_claims=[LibraryClaimBrief(id=claim.id, body=claim.body) for claim in claims],
        source_ids=source_ids,
        sources=[
            LibrarySourceBrief(
                id=source.id,
                title=source.title,
                url=source.url,
                document_reference=source.document_reference,
            )
            for source in sources
        ],
        verification_event_ids=event_ids,
        verifications=[
            LibraryVerificationBrief(
                id=event.id,
                subject_type=event.subject_type.value,
                result_status=event.result_status.value,
                method=event.method,
                mistake_reason=event.mistake_reason,
            )
            for event in events
        ],
        requests=[_request_read(item, names) for item in requests],
        created_at=entry.created_at,
    )


@router.post("/entries", response_model=LibraryEntryRead, status_code=status.HTTP_201_CREATED)
def post_entry(
    payload: LibraryEntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    entry = _guard(lambda: create_entry(db, user.id, payload))
    db.commit()
    db.refresh(entry)
    return _read_entry(db, entry)


@router.get("/search", response_model=list[LibraryEntryRead])
def search_library(q: str = Query(min_length=2), db: Session = Depends(get_db)):
    return [_read_entry(db, entry) for entry in search_entries(db, q)]


@router.get("/entries/{entry_id}", response_model=LibraryEntryRead)
def get_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(ReferenceEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Library entry not found")
    return _read_entry(db, entry)


@router.post("/entries/{entry_id}/reevaluations", response_model=ReevaluationRead, status_code=201)
def request_entry_reevaluation(
    entry_id: int,
    payload: ReevaluationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    entry = db.get(ReferenceEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Library entry not found")
    request = _guard(lambda: open_request(
        db,
        user.id,
        reason=payload.reason,
        evidence_note=payload.evidence_note,
        new_source_id=payload.new_source_id,
        entry=entry,
    ))
    db.commit()
    db.refresh(request)
    return request


@router.post("/reevaluations", response_model=ReevaluationRead, status_code=201)
def request_claim_reevaluation(
    payload: ReevaluationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    knowledge = db.get(KnowledgeClaim, payload.knowledge_claim_id) if payload.knowledge_claim_id else None
    claim = db.get(Claim, payload.claim_id) if payload.claim_id else None
    if payload.knowledge_claim_id and knowledge is None:
        raise HTTPException(status_code=404, detail="Knowledge claim not found")
    if payload.claim_id and claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    request = _guard(lambda: open_request(
        db,
        user.id,
        reason=payload.reason,
        evidence_note=payload.evidence_note,
        new_source_id=payload.new_source_id,
        knowledge_claim=knowledge,
        claim=claim,
    ))
    db.commit()
    db.refresh(request)
    return request


@router.post("/reevaluations/{request_id}/decision", response_model=ReevaluationRead)
def decide_reevaluation(
    request_id: int,
    payload: ReevaluationDecision,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    request = db.get(ReevaluationRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Re-evaluation request not found")
    _guard(lambda: decide_request(db, request, user.id, payload))
    db.commit()
    db.refresh(request)
    return request


@router.post("/points/{point_id}/resolve", response_model=LibraryVersionRead)
def resolve_library_point(
    point_id: int,
    payload: PointResolve,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    point = db.get(LibraryPoint, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="Library point not found")
    version = _guard(lambda: resolve_point(db, point, user.id, payload))
    db.commit()
    db.refresh(version)
    return version


@router.post("/invalidations", status_code=201)
def post_invalidation(
    payload: InvalidationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    invalidation = _guard(lambda: record_upstream_invalidation(db, user, payload))
    db.commit()
    return {
        "id": invalidation.id,
        "subject_type": invalidation.subject_type,
        "subject_id": invalidation.subject_id,
        "kind": invalidation.kind,
        "reason": invalidation.reason,
        "source_id": invalidation.source_id,
        "recorded_by_user_id": invalidation.recorded_by_user_id,
        "actor": invalidation.actor,
        "recorded_at": invalidation.recorded_at,
    }


@router.post("/invalidations/{invalidation_id}/reverse")
def post_reverse_invalidation(
    invalidation_id: int,
    payload: InvalidationReverse,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    from app.models.library import UpstreamInvalidation

    invalidation = db.get(UpstreamInvalidation, invalidation_id)
    if invalidation is None:
        raise HTTPException(status_code=404, detail="Invalidation not found")
    _guard(lambda: reverse_upstream_invalidation(db, invalidation, user, payload.reason))
    db.commit()
    return {
        "id": invalidation.id,
        "reversed_reason": invalidation.reversed_reason,
        "reversed_by_user_id": invalidation.reversed_by_user_id,
        "actor": invalidation.actor,
    }


def enqueue_after(job_ids: list[int]) -> None:
    for job_id in job_ids:
        enqueue_research_job(job_id)
