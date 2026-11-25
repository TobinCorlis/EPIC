"""Overturn a recorded verification without erasing that it happened.

A successful challenge, or a recorded mistake in the verification itself,
removes verified/archived status and sets confidence to NULL (unknown).
The history tag keeps the event id and date. A mistake is labelled
'invalidated: ...' and is not described as a legitimate past verification.
"""
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.models.argument import ArgumentNode, VerificationStatus
from app.models.auth import User
from app.models.claim import Claim
from app.models.correction import ClaimCorrection
from app.models.evidence import ClaimEvidence, Source, SourceVerificationStatus
from app.models.knowledge import KnowledgeClaim, KnowledgeStatus
from app.models.status_history import StatusHistory
from app.models.verification import RecordedVerificationStatus, VerificationEvent, VerificationSubject


def _latest_event(db: Session, subject_type: VerificationSubject, subject_id: int) -> VerificationEvent | None:
    return (
        db.query(VerificationEvent)
        .filter(
            VerificationEvent.subject_type == subject_type,
            VerificationEvent.subject_id == subject_id,
            VerificationEvent.result_status == RecordedVerificationStatus.verified,
        )
        .order_by(VerificationEvent.id.desc())
        .first()
    )


def _history_note(event: VerificationEvent) -> str:
    when = event.created_at.date().isoformat()
    if event.mistake_reason:
        return (
            f"invalidated: {event.mistake_reason}. "
            f"Verification event {event.id} on {when} is not a legitimate past verification."
        )
    return f"Previously verified on {when} by verification event {event.id}."


def _refresh_notes(db: Session, event: VerificationEvent) -> None:
    note = _history_note(event)
    for row in db.query(StatusHistory).filter(StatusHistory.verification_event_id == event.id):
        row.note = note


def _demote_subject(db: Session, event: VerificationEvent, user: User | None, reason: str) -> None:
    if event.subject_type == VerificationSubject.knowledge_claim:
        subject = db.get(KnowledgeClaim, event.subject_id)
        if not subject or subject.status not in {KnowledgeStatus.verified, KnowledgeStatus.archived}:
            return
        previous = subject.status.value
        subject.status = KnowledgeStatus.unverified
        subject.confidence_score = None
        if user is not None:
            db.add(ClaimCorrection(
                knowledge_claim_id=subject.id,
                original_body=subject.body,
                corrected_body=subject.body,
                reason=reason,
                kind="verification_overturned",
                author_user_id=user.id,
            ))
    elif event.subject_type == VerificationSubject.argument_node:
        subject = db.get(ArgumentNode, event.subject_id)
        if not subject or subject.verification_status not in {VerificationStatus.verified, VerificationStatus.archived}:
            return
        previous = subject.verification_status.value
        subject.verification_status = VerificationStatus.unverified
        if user is not None and subject.claim_id is not None:
            claim = db.get(Claim, subject.claim_id)
            if claim is not None:
                db.add(ClaimCorrection(
                    claim_id=claim.id,
                    original_body=claim.body,
                    corrected_body=claim.body,
                    reason=reason,
                    kind="verification_overturned",
                    author_user_id=user.id,
                ))
    elif event.subject_type == VerificationSubject.source:
        subject = db.get(Source, event.subject_id)
        if not subject or subject.verification_status not in {SourceVerificationStatus.verified, SourceVerificationStatus.archived}:
            return
        previous = subject.verification_status.value
        subject.verification_status = SourceVerificationStatus.unverified
    else:
        return
    db.add(StatusHistory(
        subject_type=event.subject_type.value,
        subject_id=event.subject_id,
        previous_status=previous,
        new_status="unverified",
        note=_history_note(event),
        verification_event_id=event.id,
    ))


def overturn_verified_for_debate_claim(db: Session, claim_id: int, user: User | None, reason: str) -> None:
    """Remove verified status that a real event recorded, after a successful challenge."""
    knowledge_ids = [
        row[0]
        for row in db.query(KnowledgeClaim.id).filter(KnowledgeClaim.originating_claim_id == claim_id).all()
    ]
    argument_ids = [
        row[0]
        for row in db.query(ArgumentNode.id).filter(ArgumentNode.claim_id == claim_id).all()
    ]
    source_ids = [
        row[0]
        for row in (
            db.query(ClaimEvidence.citation_id)
            .filter(ClaimEvidence.claim_id == claim_id)
            .all()
        )
    ]
    events: list[VerificationEvent] = []
    if knowledge_ids:
        events.extend(
            db.query(VerificationEvent)
            .filter(
                VerificationEvent.subject_type == VerificationSubject.knowledge_claim,
                VerificationEvent.subject_id.in_(knowledge_ids),
                VerificationEvent.result_status == RecordedVerificationStatus.verified,
            )
            .all()
        )
    if argument_ids:
        events.extend(
            db.query(VerificationEvent)
            .filter(
                VerificationEvent.subject_type == VerificationSubject.argument_node,
                VerificationEvent.subject_id.in_(argument_ids),
                VerificationEvent.result_status == RecordedVerificationStatus.verified,
            )
            .all()
        )
    # Sources are handled only through the citation's source id.
    from app.models.evidence import Citation

    if source_ids:
        real_source_ids = [
            row[0]
            for row in db.query(Citation.source_id).filter(Citation.id.in_(source_ids)).all()
        ]
        if real_source_ids:
            events.extend(
                db.query(VerificationEvent)
                .filter(
                    VerificationEvent.subject_type == VerificationSubject.source,
                    VerificationEvent.subject_id.in_(real_source_ids),
                    VerificationEvent.result_status == RecordedVerificationStatus.verified,
                )
                .all()
            )
    seen = set()
    for event in events:
        if event.id in seen:
            continue
        seen.add(event.id)
        _demote_subject(db, event, user, reason)
    from app.services.reference_library import mark_stale_for_claim

    mark_stale_for_claim(db, claim_id)


def record_verification_mistake(db: Session, event: VerificationEvent, user: User, reason: str) -> None:
    event.mistake_reason = reason.strip()
    event.mistake_recorded_at = utcnow()
    event.mistake_recorded_by_user_id = user.id
    _refresh_notes(db, event)
    _demote_subject(db, event, user, f"invalidated: {event.mistake_reason}")
