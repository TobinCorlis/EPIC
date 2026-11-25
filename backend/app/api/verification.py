
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.authorization import require_authenticated
from app.core.database import get_db
from app.models.argument import ArgumentNode, VerificationStatus
from app.models.auth import User
from app.models.evidence import Source, SourceVerificationStatus
from app.models.knowledge import KnowledgeClaim, KnowledgeStatus
from app.models.verification import RecordedVerificationStatus, VerificationEvent, VerificationSubject
from app.schemas.verification import VerificationEventCreate, VerificationEventRead, VerificationMistakeCreate
from app.services.verification_history import record_verification_mistake
from app.core.clock import utcnow

router = APIRouter(prefix="/verification-events", tags=["verification"])


def _apply_status(db: Session, payload: VerificationEventCreate) -> None:
    recorded = payload.result_status.value
    if payload.subject_type == VerificationSubject.argument_node:
        subject = db.get(ArgumentNode, payload.subject_id)
        if not subject:
            raise HTTPException(status_code=404, detail="Argument node not found")
        subject.verification_status = VerificationStatus(recorded)
        return
    if payload.subject_type == VerificationSubject.knowledge_claim:
        subject = db.get(KnowledgeClaim, payload.subject_id)
        if not subject:
            raise HTTPException(status_code=404, detail="Knowledge claim not found")
        subject.status = KnowledgeStatus(recorded)
        return
    source = db.get(Source, payload.subject_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.verification_status = SourceVerificationStatus(recorded)
    if payload.archive_url:
        source.archive_url = payload.archive_url
    if payload.result_status == RecordedVerificationStatus.archived:
        source.archived_at = utcnow()


def _claim_ids_for_verification(db: Session, payload: VerificationEventCreate) -> list[int]:
    if payload.subject_type == VerificationSubject.knowledge_claim:
        subject = db.get(KnowledgeClaim, payload.subject_id)
        if subject and subject.originating_claim_id:
            return [subject.originating_claim_id]
        return []
    if payload.subject_type == VerificationSubject.argument_node:
        subject = db.get(ArgumentNode, payload.subject_id)
        if subject and subject.claim_id:
            return [subject.claim_id]
        return []
    return []


@router.post("", response_model=VerificationEventRead, status_code=status.HTTP_201_CREATED)
def create_verification_event(
    payload: VerificationEventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    if payload.result_status == RecordedVerificationStatus.verified and payload.subject_type == VerificationSubject.source:
        from app.services.factcheck.status import findability_for_source, has_retraction

        if has_retraction(db, payload.subject_id) or findability_for_source(db, payload.subject_id) != "found":
            raise HTTPException(
                status_code=409,
                detail="Automated checks have not passed. The source cannot be marked verified.",
            )
    if payload.result_status == RecordedVerificationStatus.verified and payload.subject_type != VerificationSubject.source:
        from app.models.claim import Claim
        from app.services.claim_confidence import SUPPORT_RULE, support_qualifies

        claim_ids = _claim_ids_for_verification(db, payload)
        if not support_qualifies(db, claim_ids):
            for claim_id in claim_ids:
                claim = db.get(Claim, claim_id)
                if claim is not None:
                    claim.needs_review = True
            db.commit()
            raise HTTPException(status_code=409, detail=SUPPORT_RULE)
        from app.models.evidence import Citation, ClaimEvidence
        from app.services.factcheck.status import findability_for_source, has_retraction

        source_ids = {
            row[0]
            for row in (
                db.query(Citation.source_id)
                .join(ClaimEvidence, ClaimEvidence.citation_id == Citation.id)
                .filter(ClaimEvidence.claim_id.in_(claim_ids or [0]))
                .all()
            )
        }
        for source_id in source_ids:
            status_name = findability_for_source(db, source_id)
            if has_retraction(db, source_id) or status_name in {"not_findable", "check_failed", "low_confidence"}:
                raise HTTPException(
                    status_code=409,
                    detail="Automated checks have not passed. The claim cannot be marked verified.",
                )
    _apply_status(db, payload)
    event = VerificationEvent(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        result_status=payload.result_status,
        actor_user_id=user.id,
        method=payload.method,
        archive_url=payload.archive_url,
        snapshot_hash=payload.snapshot_hash,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("", response_model=list[VerificationEventRead])
def list_verification_events(
    subject_type: VerificationSubject,
    subject_id: int,
    db: Session = Depends(get_db),
):
    return (
        db.query(VerificationEvent)
        .filter(
            VerificationEvent.subject_type == subject_type,
            VerificationEvent.subject_id == subject_id,
        )
        .order_by(VerificationEvent.id)
        .all()
    )


@router.post("/{event_id}/mistake", response_model=VerificationEventRead)
def mark_verification_mistake(
    event_id: int,
    payload: VerificationMistakeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    event = db.get(VerificationEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Verification event not found")
    record_verification_mistake(db, event, user, payload.reason)
    db.commit()
    db.refresh(event)
    return event
