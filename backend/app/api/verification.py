from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.authorization import require_authenticated
from app.core.database import get_db
from app.models.argument import ArgumentNode, VerificationStatus
from app.models.auth import User
from app.models.evidence import Source, SourceVerificationStatus
from app.models.knowledge import KnowledgeClaim, KnowledgeStatus
from app.models.verification import RecordedVerificationStatus, VerificationEvent, VerificationSubject
from app.schemas.verification import VerificationEventCreate, VerificationEventRead

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
        source.archived_at = datetime.utcnow()


@router.post("", response_model=VerificationEventRead, status_code=status.HTTP_201_CREATED)
def create_verification_event(
    payload: VerificationEventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
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
