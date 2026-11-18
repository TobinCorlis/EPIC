"""Reference library: reuse recorded answers, and keep every later decision as a new version.

A match requires the question text and the user-entered scope fields. A near
text match with a different scope is a different question. A stale entry is
not served as the current answer. Automated research of a new point stays on
the research-job path and is not implemented.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.models.claim import Claim
from app.models.correction import ClaimCorrection
from app.models.debate import Debate
from app.models.evidence import Citation, ClaimEvidence, EvidenceStance, Source
from app.models.knowledge import KnowledgeClaim, KnowledgeStatus, ResearchJob, ResearchJobEvent, ResearchJobStatus
from app.models.library import (
    LibraryPoint,
    ReferenceEntry,
    ReferenceEntryClaim,
    ReferenceEntryDebate,
    ReferenceEntrySource,
    ReferenceEntryVerification,
    ReferenceEntryVersion,
    ReevaluationRequest,
    UpstreamInvalidation,
)
from app.models.verification import VerificationEvent
from app.services.claim_confidence import assess_claim
from app.services.evidence_scoring import TIER_RANK, effective_source_type

NEW_POINT = "new point, not yet researched"
_TOKEN = re.compile(r"[a-z0-9]+")


class LibraryError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _norm(value: str | None) -> str:
    return " ".join(_TOKEN.findall((value or "").lower()))


def _tokens(value: str | None) -> set[str]:
    return set(_TOKEN.findall((value or "").lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def questions_match(left: str, right: str) -> bool:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return False
    return a == b or _jaccard(a, b) >= 0.72


def scopes_match(entry: ReferenceEntry, population, timeframe, geography, metric) -> bool:
    return (
        _norm(entry.question_population) == _norm(population)
        and _norm(entry.question_timeframe) == _norm(timeframe)
        and _norm(entry.question_geography) == _norm(geography)
        and _norm(entry.question_metric) == _norm(metric)
    )


def ensure_entry_status(db: Session, entry: ReferenceEntry) -> None:
    """Downgrade a supported or verified version that lacks reviewed evidence.

    The previous version stays. The replacement is a new version, flagged for review.
    """
    from app.services.claim_confidence import SUPPORT_RULE, support_qualifies

    current = latest_version(db, entry.id)
    if current is None or current.status not in {"supported", "verified"}:
        return
    claim_ids = [
        row[0]
        for row in db.query(ReferenceEntryClaim.claim_id).filter(ReferenceEntryClaim.entry_id == entry.id).all()
    ]
    if support_qualifies(db, claim_ids):
        return
    entry.needs_review = True
    version = append_version(
        db,
        entry,
        None,
        outcome="downgraded",
        change_log=f"Downgraded: {SUPPORT_RULE}",
        status="unresolved",
    )
    if claim_ids:
        version.confidence_json = _confidence_json(db, claim_ids)


def latest_version(db: Session, entry_id: int) -> ReferenceEntryVersion | None:
    return (
        db.query(ReferenceEntryVersion)
        .filter(ReferenceEntryVersion.entry_id == entry_id)
        .order_by(ReferenceEntryVersion.version_number.desc())
        .first()
    )


def find_entry(db: Session, question: str, population, timeframe, geography, metric) -> ReferenceEntry | None:
    best = None
    best_score = 0.0
    asked = _tokens(question)
    for entry in db.query(ReferenceEntry).order_by(ReferenceEntry.id).all():
        if not scopes_match(entry, population, timeframe, geography, metric):
            continue
        if not questions_match(question, entry.question):
            continue
        score = _jaccard(asked, _tokens(entry.question))
        if score > best_score:
            best = entry
            best_score = score
    return best


def search_entries(db: Session, query: str) -> list[ReferenceEntry]:
    wanted = _tokens(query)
    if not wanted and not query.strip():
        return []
    hits = []
    for entry in db.query(ReferenceEntry).order_by(ReferenceEntry.id).all():
        text = _tokens(entry.question)
        if query.strip().lower() in entry.question.lower() or (wanted and wanted & text):
            hits.append(entry)
    return hits


def _confidence_json(db: Session, claim_ids: list[int]) -> str:
    breakdowns = [assess_claim(db, claim_id) for claim_id in claim_ids]
    return json.dumps(breakdowns)


def _link_evidence_ids(db: Session, claim_ids: list[int]) -> list[int]:
    if not claim_ids:
        return []
    rows = (
        db.query(Citation.source_id)
        .join(ClaimEvidence, ClaimEvidence.citation_id == Citation.id)
        .filter(ClaimEvidence.claim_id.in_(claim_ids), ClaimEvidence.stance == EvidenceStance.supports)
        .all()
    )
    return sorted({row[0] for row in rows})


def create_entry(db: Session, user_id: int, payload) -> ReferenceEntry:
    claims = []
    for claim_id in payload.supporting_claim_ids:
        claim = db.get(Claim, claim_id)
        if claim is None:
            raise LibraryError(404, f"Claim {claim_id} not found")
        if not db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == claim_id).first():
            raise LibraryError(422, f"Claim {claim_id} has no recorded evidence")
        claims.append(claim)
    if payload.status == "verified" and not payload.verification_event_ids:
        raise LibraryError(422, "A verified library entry requires a recorded verification event")
    for event_id in payload.verification_event_ids:
        event = db.get(VerificationEvent, event_id)
        if event is None:
            raise LibraryError(404, f"Verification event {event_id} not found")
        if payload.status == "verified" and (event.result_status.value != "verified" or event.mistake_reason):
            raise LibraryError(422, f"Verification event {event_id} is not a current verification")
    if payload.direct_answer == "gap" and not (payload.uncertainty or "").strip():
        raise LibraryError(422, "A gap answer requires an uncertainty statement")
    for source_id in payload.source_ids:
        if db.get(Source, source_id) is None:
            raise LibraryError(404, f"Source {source_id} not found")

    entry = ReferenceEntry(
        question=payload.question.strip(),
        question_population=payload.question_population,
        question_timeframe=payload.question_timeframe,
        question_geography=payload.question_geography,
        question_metric=payload.question_metric,
    )
    db.add(entry)
    db.flush()
    source_ids = set(payload.source_ids) | set(_link_evidence_ids(db, payload.supporting_claim_ids))
    for claim in claims:
        db.add(ReferenceEntryClaim(entry_id=entry.id, claim_id=claim.id))
    for source_id in source_ids:
        db.add(ReferenceEntrySource(entry_id=entry.id, source_id=source_id))
    for event_id in payload.verification_event_ids:
        db.add(ReferenceEntryVerification(entry_id=entry.id, verification_event_id=event_id))
    from app.services.claim_confidence import SUPPORT_RULE, support_qualifies

    status = payload.status
    change_log = payload.change_log.strip()
    if status in {"supported", "verified"} and not support_qualifies(db, payload.supporting_claim_ids):
        status = "unresolved"
        entry.needs_review = True
        change_log = f"{change_log} Downgraded: {SUPPORT_RULE}"
    now = utcnow()
    version = ReferenceEntryVersion(
        entry_id=entry.id,
        version_number=1,
        direct_answer=payload.direct_answer,
        status=status,
        facts=payload.facts.strip(),
        interpretation=payload.interpretation.strip(),
        uncertainty=(payload.uncertainty or "").strip() or None,
        date_resolved=now,
        last_reviewed_at=now,
        change_log=change_log,
        outcome="initial",
        confidence_json=_confidence_json(db, payload.supporting_claim_ids),
        created_by_user_id=user_id,
    )
    db.add(version)
    db.flush()
    for point in payload.covered_points:
        text = point.strip()
        if text:
            db.add(LibraryPoint(
                entry_id=entry.id,
                body=text,
                status="covered",
                covered_by_version_id=version.id,
            ))
    return entry


def append_version(
    db: Session,
    entry: ReferenceEntry,
    user_id: int | None,
    *,
    outcome: str,
    change_log: str,
    winning_source_id: int | None = None,
    winning_reason: str | None = None,
    direct_answer: str | None = None,
    status: str | None = None,
    facts: str | None = None,
    interpretation: str | None = None,
    uncertainty: str | None = None,
) -> ReferenceEntryVersion:
    previous = latest_version(db, entry.id)
    if previous is None:
        raise LibraryError(409, "The library entry has no version to revise")
    now = utcnow()
    version = ReferenceEntryVersion(
        entry_id=entry.id,
        version_number=previous.version_number + 1,
        direct_answer=direct_answer or previous.direct_answer,
        status=status or previous.status,
        facts=facts.strip() if facts else previous.facts,
        interpretation=interpretation.strip() if interpretation else previous.interpretation,
        uncertainty=uncertainty if uncertainty is not None else previous.uncertainty,
        date_resolved=now,
        last_reviewed_at=now,
        change_log=change_log.strip(),
        outcome=outcome,
        winning_source_id=winning_source_id,
        winning_reason=winning_reason,
        confidence_json=previous.confidence_json,
        created_by_user_id=user_id,
    )
    db.add(version)
    db.flush()
    if outcome == "revised":
        entry.stale = False
    return version


def annotate_debate(db: Session, debate: Debate) -> None:
    link = (
        db.query(ReferenceEntryDebate)
        .filter(ReferenceEntryDebate.debate_id == debate.id)
        .order_by(ReferenceEntryDebate.id.desc())
        .first()
    )
    debate.library_entry_id = None
    debate.library_served = False
    debate.library_last_reviewed_at = None
    debate.library_reevaluation_pending = False
    debate.library_notice = None
    if link is None:
        return
    entry = db.get(ReferenceEntry, link.entry_id)
    version = latest_version(db, entry.id) if entry else None
    debate.library_entry_id = entry.id
    debate.library_reevaluation_pending = bool(entry.reevaluation_pending)
    debate.library_last_reviewed_at = version.last_reviewed_at if version else None
    if entry.stale or debate.library_stale or not link.served:
        debate.library_stale = True
        debate.library_served = False
        debate.library_notice = (
            "A library entry matches this question, but it is stale and is not the current answer."
        )
        return
    debate.library_served = True
    reviewed = version.last_reviewed_at.date().isoformat() if version and version.last_reviewed_at else "unknown"
    pending = " Re-evaluation pending." if entry.reevaluation_pending else ""
    debate.library_notice = f"Answer attached from the reference library. Last reviewed {reviewed}.{pending}"


def annotate_point(db: Session, subject, *, claim_id: int | None = None, argument_node_id: int | None = None) -> None:
    query = db.query(LibraryPoint)
    if claim_id is not None:
        query = query.filter(LibraryPoint.claim_id == claim_id)
    else:
        query = query.filter(LibraryPoint.argument_node_id == argument_node_id)
    point = query.order_by(LibraryPoint.id.desc()).first()
    subject.library_entry_id = point.entry_id if point else None
    subject.library_point_id = point.id if point else None
    subject.library_point_status = point.status if point else None
    subject.library_notice = None
    if point is None:
        return
    if point.status == NEW_POINT:
        subject.library_notice = (
            "New point, not yet researched. Automated research is not implemented."
        )
    elif point.status == "covered":
        subject.library_notice = (
            f"This point is already covered by library entry {point.entry_id}, "
            f"version {point.covered_by_version_id}."
        )


def consider_debate(db: Session, debate: Debate) -> None:
    entry = find_entry(
        db,
        debate.fixed_question,
        debate.question_population,
        debate.question_timeframe,
        debate.question_geography,
        debate.question_metric,
    )
    if entry is None:
        return
    served = not entry.stale
    db.add(ReferenceEntryDebate(entry_id=entry.id, debate_id=debate.id, served=served))
    if not served:
        debate.library_stale = True


def _attached_entry(db: Session, debate: Debate) -> ReferenceEntry | None:
    link = (
        db.query(ReferenceEntryDebate)
        .filter(ReferenceEntryDebate.debate_id == debate.id, ReferenceEntryDebate.served.is_(True))
        .order_by(ReferenceEntryDebate.id.desc())
        .first()
    )
    if link is None:
        return None
    entry = db.get(ReferenceEntry, link.entry_id)
    if entry is None or entry.stale:
        return None
    return entry


def _matching_covered_point(db: Session, entry: ReferenceEntry, body: str) -> LibraryPoint | None:
    incoming = _tokens(body)
    best = None
    best_score = 0.0
    points = (
        db.query(LibraryPoint)
        .filter(LibraryPoint.entry_id == entry.id, LibraryPoint.status == "covered", LibraryPoint.debate_id.is_(None))
        .all()
    )
    for point in points:
        score = _jaccard(incoming, _tokens(point.body))
        if _norm(body) == _norm(point.body) or score >= 0.5:
            if score >= best_score:
                best = point
                best_score = score
    return best


def consider_text(
    db: Session,
    debate: Debate,
    body: str,
    *,
    claim_id: int | None = None,
    argument_node_id: int | None = None,
) -> list[int]:
    """Return research job ids that the caller should enqueue after commit."""
    entry = _attached_entry(db, debate)
    if entry is None:
        entry = find_entry(
            db,
            body,
            debate.question_population,
            debate.question_timeframe,
            debate.question_geography,
            debate.question_metric,
        )
        if entry is None or entry.stale:
            return []
    covered = _matching_covered_point(db, entry, body)
    if covered is not None:
        db.add(LibraryPoint(
            entry_id=entry.id,
            debate_id=debate.id,
            claim_id=claim_id,
            argument_node_id=argument_node_id,
            body=body,
            status="covered",
            covered_by_version_id=covered.covered_by_version_id,
        ))
        return []
    job = ResearchJob(
        query=f"{NEW_POINT}: {body}",
        status=ResearchJobStatus.queued,
        current_step="Queued",
    )
    db.add(job)
    db.flush()
    db.add(ResearchJobEvent(
        job_id=job.id,
        progress_percent=0,
        step="Queued",
        message="New point, not yet researched. Automated research is not implemented.",
    ))
    db.add(LibraryPoint(
        entry_id=entry.id,
        debate_id=debate.id,
        claim_id=claim_id,
        argument_node_id=argument_node_id,
        body=body,
        status=NEW_POINT,
        research_job_id=job.id,
    ))
    return [job.id]


def mark_stale_for_claim(db: Session, claim_id: int) -> None:
    entry_ids = {
        row[0]
        for row in db.query(ReferenceEntryClaim.entry_id).filter(ReferenceEntryClaim.claim_id == claim_id).all()
    }
    claim = db.get(Claim, claim_id)
    if claim is not None:
        debate = db.get(Debate, claim.debate_id)
        if debate is not None:
            debate.library_stale = True
            entry_ids.update(
                row[0]
                for row in db.query(ReferenceEntryDebate.entry_id)
                .filter(ReferenceEntryDebate.debate_id == debate.id)
                .all()
            )
    for entry_id in entry_ids:
        entry = db.get(ReferenceEntry, entry_id)
        if entry is not None:
            entry.stale = True
            _flag_attached_debates(db, entry)


def _flag_attached_debates(db: Session, entry: ReferenceEntry) -> None:
    debate_ids = [
        row[0]
        for row in db.query(ReferenceEntryDebate.debate_id).filter(ReferenceEntryDebate.entry_id == entry.id).all()
    ]
    if not debate_ids:
        return
    for debate in db.query(Debate).filter(Debate.id.in_(debate_ids)).all():
        debate.library_stale = True
        entry_link = (
            db.query(ReferenceEntryDebate)
            .filter(ReferenceEntryDebate.entry_id == entry.id, ReferenceEntryDebate.debate_id == debate.id)
            .first()
        )
        if entry_link is not None:
            entry_link.served = False


def entries_for_source(db: Session, source_id: int) -> list[ReferenceEntry]:
    ids = [
        row[0]
        for row in db.query(ReferenceEntrySource.entry_id).filter(ReferenceEntrySource.source_id == source_id).all()
    ]
    if not ids:
        return []
    return db.query(ReferenceEntry).filter(ReferenceEntry.id.in_(ids)).all()


def open_request(
    db: Session,
    user_id: int,
    *,
    reason: str,
    evidence_note: str | None,
    new_source_id: int | None,
    entry: ReferenceEntry | None = None,
    knowledge_claim: KnowledgeClaim | None = None,
    claim: Claim | None = None,
) -> ReevaluationRequest:
    if new_source_id is not None and db.get(Source, new_source_id) is None:
        raise LibraryError(404, "Source not found")
    if entry is None and knowledge_claim is None and claim is None:
        raise LibraryError(422, "A re-evaluation request needs a library entry or a claim")
    if knowledge_claim is not None and knowledge_claim.status != KnowledgeStatus.verified:
        raise LibraryError(409, "Only a verified claim can be submitted for re-evaluation")
    request = ReevaluationRequest(
        entry_id=entry.id if entry else None,
        knowledge_claim_id=knowledge_claim.id if knowledge_claim else None,
        claim_id=claim.id if claim else None,
        reason=reason.strip(),
        evidence_note=(evidence_note or "").strip() or None,
        new_source_id=new_source_id,
        requested_by_user_id=user_id,
        status="open",
    )
    db.add(request)
    if entry is not None:
        entry.reevaluation_pending = True
    return request


def _candidate_sources(db: Session, request: ReevaluationRequest, entry: ReferenceEntry | None) -> list[Source]:
    ids: set[int] = set()
    if entry is not None:
        ids.update(
            row[0]
            for row in db.query(ReferenceEntrySource.source_id).filter(ReferenceEntrySource.entry_id == entry.id).all()
        )
    if request.new_source_id is not None:
        ids.add(request.new_source_id)
    if request.claim_id is not None:
        ids.update(_link_evidence_ids(db, [request.claim_id]))
    if request.knowledge_claim_id is not None:
        knowledge = db.get(KnowledgeClaim, request.knowledge_claim_id)
        if knowledge and knowledge.originating_claim_id:
            ids.update(_link_evidence_ids(db, [knowledge.originating_claim_id]))
    if not ids:
        return []
    return db.query(Source).filter(Source.id.in_(ids)).all()


def _invalidated_source_ids(db: Session, source_ids: set[int]) -> set[int]:
    if not source_ids:
        return set()
    rows = (
        db.query(UpstreamInvalidation.subject_id)
        .filter(
            UpstreamInvalidation.subject_type == "source",
            UpstreamInvalidation.subject_id.in_(source_ids),
        )
        .all()
    )
    return {row[0] for row in rows}


def weigh_sources(db: Session, sources: list[Source]) -> tuple[Source | None, str]:
    """Most reliable evidence wins. Recency breaks a tie. Newer does not beat more reliable."""
    from app.services.claim_confidence import source_record

    if not sources:
        return None, "No recorded evidence was available to weigh."
    invalidated = _invalidated_source_ids(db, {source.id for source in sources})
    scored = []
    for source in sources:
        if source.id in invalidated:
            scored.append((source, None, source.publication_date or source.created_at, "invalidated"))
            continue
        if getattr(source, "record_status", "not_checked") == "no_record_found":
            scored.append((source, None, source.publication_date or source.created_at, "cited source: no record found"))
            continue
        effective = effective_source_type(source.source_type, source.source_type_reviewed)
        tier_factor = TIER_RANK[effective] / 8
        record = source_record(db, source.id)
        if record.track_factor is None:
            reliability = tier_factor
            track = "no track record, treated as unknown and not as zero"
        else:
            reliability = tier_factor * record.track_factor
            track = f"track factor {record.track_factor:.3f}"
        when = source.publication_date or source.created_at
        scored.append((source, reliability, when, f"tier factor {tier_factor:.3f}; {track}"))
    reliable = [item for item in scored if item[1] is not None]
    if not reliable:
        if any(item[3] == "cited source: no record found" for item in scored):
            return None, "cited source: no record found. No findable source was available to weigh."
        notice = next((item[0] for item in scored), None)
        return notice, (
            "Every compared source is invalidated. The invalidation is the deciding record, "
            "not a newer or weaker source."
        )
    reliable.sort(key=lambda item: (item[1], item[2] or datetime.min), reverse=True)
    winner, reliability, when, detail = reliable[0]
    lines = [
        f"Source {winner.id} ('{winner.title}') wins with reliability {reliability:.3f} ({detail})."
    ]
    for source, other_reliability, other_when, other_detail in reliable[1:]:
        newer = other_when and when and other_when > when
        if other_reliability < reliability:
            lines.append(
                f"Source {source.id} ('{source.title}') has reliability {other_reliability:.3f} ({other_detail}). "
                + (
                    "It is newer and does not override the more reliable source."
                    if newer
                    else "It does not override the more reliable source."
                )
            )
        else:
            lines.append(
                f"Source {source.id} ties on reliability. "
                "The more recent of the equally reliable sources is preferred, and it did not win this comparison."
            )
    for source, _reliability, _when, _detail in scored:
        if source.id in invalidated:
            lines.append(f"Source {source.id} ('{source.title}') is invalidated and is not treated as reliable evidence.")
    return winner, " ".join(lines)


def _entries_for_request(db: Session, request: ReevaluationRequest) -> list[ReferenceEntry]:
    if request.entry_id is not None:
        entry = db.get(ReferenceEntry, request.entry_id)
        return [entry] if entry else []
    claim_ids = []
    if request.claim_id is not None:
        claim_ids.append(request.claim_id)
    if request.knowledge_claim_id is not None:
        knowledge = db.get(KnowledgeClaim, request.knowledge_claim_id)
        if knowledge and knowledge.originating_claim_id:
            claim_ids.append(knowledge.originating_claim_id)
    if not claim_ids:
        return []
    ids = [
        row[0]
        for row in db.query(ReferenceEntryClaim.entry_id).filter(ReferenceEntryClaim.claim_id.in_(claim_ids)).all()
    ]
    if not ids:
        return []
    return db.query(ReferenceEntry).filter(ReferenceEntry.id.in_(ids)).all()


def decide_request(db: Session, request: ReevaluationRequest, user_id: int, payload) -> ReevaluationRequest:
    if request.status != "open":
        raise LibraryError(409, "This re-evaluation request is already decided")
    entries = _entries_for_request(db, request)
    if not entries:
        raise LibraryError(409, "This request has no library entry to version")
    entry = entries[0]
    sources = _candidate_sources(db, request, entry)
    winner, why = weigh_sources(db, sources)
    current_ids = {
        row[0]
        for row in db.query(ReferenceEntrySource.source_id).filter(ReferenceEntrySource.entry_id == entry.id).all()
    }
    invalidated = _invalidated_source_ids(db, current_ids | ({request.new_source_id} if request.new_source_id else set()))
    outcome = payload.outcome
    if outcome == "upheld":
        if entry.stale or (winner is not None and winner.id in invalidated):
            raise LibraryError(409, "A stale or invalidated record cannot be upheld as the current answer")
        if winner is None or winner.id not in current_ids:
            raise LibraryError(409, "The weighed evidence does not support upholding the current answer")
    elif outcome == "revised":
        if winner is None or winner.id in invalidated or winner.id in current_ids and request.new_source_id != winner.id:
            raise LibraryError(409, "A revision requires the weighed winner to be reliable new evidence")
        if request.new_source_id is None or winner.id != request.new_source_id:
            raise LibraryError(409, "The newer or added source did not win on reliability")
        if not payload.facts or not payload.interpretation or not payload.direct_answer:
            raise LibraryError(422, "A revised version requires the answer, the facts, and the interpretation")
    elif outcome == "overturned":
        if not invalidated and not (winner is not None and winner.id in invalidated):
            # Allow overturn when any supporting source or linked verification was invalidated.
            verification_ids = [
                row[0]
                for row in db.query(ReferenceEntryVerification.verification_event_id)
                .filter(ReferenceEntryVerification.entry_id == entry.id)
                .all()
            ]
            verification_invalidated = False
            if verification_ids:
                verification_invalidated = (
                    db.query(UpstreamInvalidation)
                    .filter(
                        UpstreamInvalidation.subject_type == "verification_event",
                        UpstreamInvalidation.subject_id.in_(verification_ids),
                    )
                    .first()
                    is not None
                )
            if not verification_invalidated and not invalidated:
                raise LibraryError(409, "An overturn requires an upstream invalidation of the supporting record")
    else:
        raise LibraryError(422, "Outcome must be upheld, revised, or overturned")

    if outcome == "overturned" and invalidated:
        notice_id = (
            db.query(UpstreamInvalidation.source_id)
            .filter(
                UpstreamInvalidation.subject_type == "source",
                UpstreamInvalidation.subject_id.in_(invalidated),
            )
            .order_by(UpstreamInvalidation.id.desc())
            .first()
        )
        if notice_id is not None:
            why = (
                f"{why} The deciding record is the invalidation of source {next(iter(invalidated))}, "
                f"documented by source {notice_id[0]}. The prior verification is not a legitimate past verification."
            )
            winner_id = notice_id[0]
        else:
            winner_id = winner.id if winner else None
    else:
        winner_id = winner.id if winner else None

    claim_ids = [
        row[0]
        for row in db.query(ReferenceEntryClaim.claim_id).filter(ReferenceEntryClaim.entry_id == entry.id).all()
    ]
    from app.services.claim_confidence import support_qualifies

    status = "unresolved" if outcome == "overturned" else payload.status
    if status in {"supported", "verified"} and not support_qualifies(db, claim_ids):
        status = "unresolved"
        entry.needs_review = True
    version = append_version(
        db,
        entry,
        user_id,
        outcome=outcome,
        change_log=payload.note.strip(),
        winning_source_id=winner_id,
        winning_reason=why,
        direct_answer=payload.direct_answer,
        status=status,
        facts=payload.facts,
        interpretation=payload.interpretation,
        uncertainty=payload.uncertainty,
    )
    if request.new_source_id and outcome == "revised":
        exists = (
            db.query(ReferenceEntrySource)
            .filter(
                ReferenceEntrySource.entry_id == entry.id,
                ReferenceEntrySource.source_id == request.new_source_id,
            )
            .first()
        )
        if exists is None:
            db.add(ReferenceEntrySource(entry_id=entry.id, source_id=request.new_source_id))
    if claim_ids:
        version.confidence_json = _confidence_json(db, claim_ids)
    request.status = outcome
    request.decision = payload.note.strip()
    request.winning_source_id = winner_id
    request.winning_reason = why
    request.decided_by_user_id = user_id
    request.decided_at = utcnow()
    request.resulting_version_id = version.id
    still_open = (
        db.query(ReevaluationRequest)
        .filter(ReevaluationRequest.entry_id == entry.id, ReevaluationRequest.status == "open", ReevaluationRequest.id != request.id)
        .first()
    )
    entry.reevaluation_pending = still_open is not None
    return request


def resolve_point(db: Session, point: LibraryPoint, user_id: int, payload) -> ReferenceEntryVersion:
    entry = db.get(ReferenceEntry, point.entry_id)
    if entry is None:
        raise LibraryError(404, "Library entry not found")
    if point.status != NEW_POINT:
        raise LibraryError(409, "Only a new point can be resolved into the library entry")
    for claim_id in payload.supporting_claim_ids:
        claim = db.get(Claim, claim_id)
        if claim is None or not db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == claim_id).first():
            raise LibraryError(422, f"Claim {claim_id} is not backed by recorded evidence")
        linked = (
            db.query(ReferenceEntryClaim)
            .filter(ReferenceEntryClaim.entry_id == entry.id, ReferenceEntryClaim.claim_id == claim_id)
            .first()
        )
        if linked is None:
            db.add(ReferenceEntryClaim(entry_id=entry.id, claim_id=claim_id))
    from app.services.claim_confidence import support_qualifies

    status = payload.status
    if status == "supported" and not support_qualifies(db, payload.supporting_claim_ids):
        status = "unresolved"
        entry.needs_review = True
    version = append_version(
        db,
        entry,
        user_id,
        outcome="revised",
        change_log=payload.change_log,
        direct_answer=payload.direct_answer,
        status=status,
        facts=payload.facts,
        interpretation=payload.interpretation,
        uncertainty=payload.uncertainty,
    )
    version.confidence_json = _confidence_json(db, payload.supporting_claim_ids)
    point.status = "resolved"
    point.covered_by_version_id = version.id
    db.add(LibraryPoint(
        entry_id=entry.id,
        body=point.body,
        status="covered",
        covered_by_version_id=version.id,
    ))
    return version


def record_upstream_invalidation(db: Session, user, payload) -> UpstreamInvalidation:
    from app.services.verification_history import record_verification_mistake

    notice = db.get(Source, payload.source_id)
    if notice is None:
        raise LibraryError(404, "The invalidation requires its own recorded source")
    if payload.subject_type not in {"source", "verification_event"}:
        raise LibraryError(422, "Invalidation subject must be a source or a verification event")
    if payload.kind not in {"false_information", "fabrication", "misconduct", "retraction", "error"}:
        raise LibraryError(422, "Invalidation kind is not recognized")
    if payload.subject_type == "source":
        if db.get(Source, payload.subject_id) is None:
            raise LibraryError(404, "Source not found")
    else:
        if db.get(VerificationEvent, payload.subject_id) is None:
            raise LibraryError(404, "Verification event not found")

    invalidation = UpstreamInvalidation(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        kind=payload.kind,
        reason=payload.reason.strip(),
        source_id=payload.source_id,
        recorded_by_user_id=user.id,
    )
    db.add(invalidation)
    db.flush()

    claim_ids: set[int] = set()
    events: list[VerificationEvent] = []
    if payload.subject_type == "verification_event":
        event = db.get(VerificationEvent, payload.subject_id)
        events.append(event)
        claim_ids.update(_claims_for_verification(db, event))
    else:
        events.extend(_verified_events_for_source(db, payload.subject_id))
        claim_ids.update(_claims_supported_by_source(db, payload.subject_id))
        events.extend(_verified_events_for_claims(db, claim_ids))

    seen = set()
    for event in events:
        if event.id in seen or event.mistake_reason:
            continue
        seen.add(event.id)
        record_verification_mistake(db, event, user, payload.reason.strip())

    for claim_id in claim_ids:
        claim = db.get(Claim, claim_id)
        if claim is None:
            continue
        db.add(ClaimCorrection(
            claim_id=claim.id,
            original_body=claim.body,
            corrected_body=claim.body,
            reason=f"Upstream invalidation ({payload.kind}): {payload.reason.strip()}",
            kind="upstream_invalidation",
            author_user_id=user.id,
        ))
        for knowledge in db.query(KnowledgeClaim).filter(KnowledgeClaim.originating_claim_id == claim.id):
            db.add(ClaimCorrection(
                knowledge_claim_id=knowledge.id,
                original_body=knowledge.body,
                corrected_body=knowledge.body,
                reason=f"Upstream invalidation ({payload.kind}): {payload.reason.strip()}",
                kind="upstream_invalidation",
                author_user_id=user.id,
            ))
        assess_claim(db, claim.id)
        mark_stale_for_claim(db, claim.id)

    entry_ids = set()
    if payload.subject_type == "source":
        entry_ids.update(entry.id for entry in entries_for_source(db, payload.subject_id))
    for claim_id in claim_ids:
        entry_ids.update(
            row[0]
            for row in db.query(ReferenceEntryClaim.entry_id).filter(ReferenceEntryClaim.claim_id == claim_id).all()
        )
    if payload.subject_type == "verification_event":
        entry_ids.update(
            row[0]
            for row in db.query(ReferenceEntryVerification.entry_id)
            .filter(ReferenceEntryVerification.verification_event_id == payload.subject_id)
            .all()
        )
    for entry_id in entry_ids:
        entry = db.get(ReferenceEntry, entry_id)
        if entry is None:
            continue
        entry.stale = True
        entry.reevaluation_pending = True
        _flag_attached_debates(db, entry)
        db.add(ReevaluationRequest(
            entry_id=entry.id,
            reason=f"Upstream {payload.kind}: {payload.reason.strip()}",
            evidence_note=f"Invalidation {invalidation.id} documented by source {payload.source_id}.",
            new_source_id=payload.source_id,
            requested_by_user_id=user.id,
            status="open",
        ))
    return invalidation


def _claims_supported_by_source(db: Session, source_id: int) -> set[int]:
    rows = (
        db.query(ClaimEvidence.claim_id)
        .join(Citation, Citation.id == ClaimEvidence.citation_id)
        .filter(Citation.source_id == source_id, ClaimEvidence.stance == EvidenceStance.supports)
        .all()
    )
    return {row[0] for row in rows}


def _verified_events_for_source(db: Session, source_id: int) -> list[VerificationEvent]:
    from app.models.verification import VerificationSubject

    return (
        db.query(VerificationEvent)
        .filter(
            VerificationEvent.subject_type == VerificationSubject.source,
            VerificationEvent.subject_id == source_id,
            VerificationEvent.mistake_reason.is_(None),
        )
        .all()
    )


def _verified_events_for_claims(db: Session, claim_ids: set[int]) -> list[VerificationEvent]:
    from app.models.argument import ArgumentNode
    from app.models.verification import VerificationSubject

    if not claim_ids:
        return []
    knowledge_ids = [
        row[0]
        for row in db.query(KnowledgeClaim.id).filter(KnowledgeClaim.originating_claim_id.in_(claim_ids)).all()
    ]
    argument_ids = [
        row[0]
        for row in db.query(ArgumentNode.id).filter(ArgumentNode.claim_id.in_(claim_ids)).all()
    ]
    events = []
    if knowledge_ids:
        events.extend(
            db.query(VerificationEvent)
            .filter(
                VerificationEvent.subject_type == VerificationSubject.knowledge_claim,
                VerificationEvent.subject_id.in_(knowledge_ids),
                VerificationEvent.mistake_reason.is_(None),
            )
            .all()
        )
    if argument_ids:
        events.extend(
            db.query(VerificationEvent)
            .filter(
                VerificationEvent.subject_type == VerificationSubject.argument_node,
                VerificationEvent.subject_id.in_(argument_ids),
                VerificationEvent.mistake_reason.is_(None),
            )
            .all()
        )
    return events


def _claims_for_verification(db: Session, event: VerificationEvent) -> set[int]:
    from app.models.argument import ArgumentNode
    from app.models.verification import VerificationSubject

    if event.subject_type == VerificationSubject.knowledge_claim:
        knowledge = db.get(KnowledgeClaim, event.subject_id)
        if knowledge and knowledge.originating_claim_id:
            return {knowledge.originating_claim_id}
    if event.subject_type == VerificationSubject.argument_node:
        node = db.get(ArgumentNode, event.subject_id)
        if node and node.claim_id:
            return {node.claim_id}
    if event.subject_type == VerificationSubject.source:
        return _claims_supported_by_source(db, event.subject_id)
    return set()
