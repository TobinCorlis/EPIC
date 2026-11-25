"""Run the deterministic checks and append immutable audit rows.

Verified and archived verification statuses are never set here. archive_url
is stored only when a snapshot URL comes back. A retraction uses the existing
upstream invalidation cascade when the job has an actor.
"""
from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import settings
from app.models.evidence import Citation, ClaimEvidence, Source
from app.models.factcheck import SourceCheck, VerificationJob
from app.models.library import UpstreamInvalidation
from app.services.factcheck.checkers import (
    courtlistener_check,
    crossref_checks,
    crossref_record,
    federal_register_check,
    govinfo_check,
    llm_check,
    openalex_checks,
    openalex_related,
    pubmed_checks,
    pubmed_related,
    quote_checks,
    save_page_check,
    url_check,
    wayback_check,
)
from app.services.factcheck.http import get_transport
from app.services.factcheck.text import (
    extract_doi,
    extract_federal_register,
    extract_govinfo,
    extract_opinion,
    extract_pmid,
    extract_text,
)


def enqueue_verification(db: Session, subject_type: str, subject_id: int, user_id: int | None) -> VerificationJob:
    existing = (
        db.query(VerificationJob)
        .filter(
            VerificationJob.subject_type == subject_type,
            VerificationJob.subject_id == subject_id,
            VerificationJob.status == "queued",
        )
        .order_by(VerificationJob.id)
        .first()
    )
    if existing is not None:
        return existing
    job = VerificationJob(subject_type=subject_type, subject_id=subject_id, requested_by_user_id=user_id)
    db.add(job)
    db.flush()
    return job


_drain_lock = threading.Lock()
_drainer_running = False
SYSTEM_ACTOR = "system:factcheck"
SYSTEM_EMAIL = "system-factcheck@epic.local"


def kickoff(job_id: int) -> None:
    """Start one in-process drainer. The API only enqueues; this or the worker runs the checks."""
    del job_id
    if not settings.factcheck_auto_run:
        return
    global _drainer_running
    with _drain_lock:
        if _drainer_running:
            return
        _drainer_running = True
    threading.Thread(target=_drain_queue, daemon=True, name="epic-factcheck").start()


def _drain_queue() -> None:
    global _drainer_running
    from app.services.factcheck_worker import claim_next_job

    try:
        while True:
            job_id = claim_next_job("in-process")
            if job_id is None:
                return
            process_verification_job(job_id)
    finally:
        with _drain_lock:
            _drainer_running = False


def system_factcheck_user(db: Session):
    """The actor recorded on a retraction the worker detected. It cannot sign in."""
    from app.models.auth import User, UserRole

    user = db.query(User).filter(User.email == SYSTEM_EMAIL).one_or_none()
    if user is None:
        user = User(
            email=SYSTEM_EMAIL,
            display_name=SYSTEM_ACTOR,
            password_hash="!",
            role=UserRole.member,
            is_active=False,
        )
        db.add(user)
        db.flush()
    return user


def _entered(source: Source) -> dict:
    year = source.publication_date.year if source.publication_date is not None else None
    return {"title": source.title, "author": source.author, "year": year, "journal": source.publisher}


def _persist(db: Session, source_id: int | None, drafts: list[dict]) -> list[SourceCheck]:
    rows = []
    for draft in drafts:
        row = SourceCheck(
            source_id=draft.get("source_id", source_id),
            claim_id=draft.get("claim_id"),
            citation_id=draft.get("citation_id"),
            checker_name=draft["checker_name"],
            checker_version=draft["checker_version"],
            api_name=draft["api_name"],
            query=draft["query"],
            response_id=draft.get("response_id"),
            result=draft["result"],
            match_score=draft.get("match_score"),
            http_status=draft.get("http_status"),
            final_url=draft.get("final_url"),
            content_type=draft.get("content_type"),
            content_hash=draft.get("content_hash"),
            evidence_url=draft.get("evidence_url"),
            archive_url=draft.get("archive_url"),
            archive_timestamp=draft.get("archive_timestamp"),
            matched_snippet=draft.get("matched_snippet"),
            detail=draft.get("detail") or "",
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def _apply_archive(source: Source, drafts: list[dict]) -> None:
    for draft in drafts:
        if draft.get("result") == "archived" and draft.get("archive_url"):
            source.archive_url = draft["archive_url"]
            source.archived_at = utcnow()
            return


def _apply_retraction(db: Session, source: Source, drafts: list[dict], actor_id: int | None, notice_meta: dict | None) -> None:
    notice = next((draft for draft in drafts if draft.get("result") == "retracted"), None)
    if notice is None:
        return
    for claim_id in _claim_ids(db, source.id):
        claim = db.get(__import__("app.models.claim", fromlist=["Claim"]).Claim, claim_id)
        if claim is not None:
            claim.needs_review = True
    existing = (
        db.query(UpstreamInvalidation)
        .filter(
            UpstreamInvalidation.subject_type == "source",
            UpstreamInvalidation.subject_id == source.id,
            UpstreamInvalidation.kind == "retraction",
            UpstreamInvalidation.reversed_reason.is_(None),
        )
        .first()
    )
    if existing is not None:
        return
    from app.models.auth import User
    from app.services.reference_library import LibraryError, record_upstream_invalidation

    actor_name = None
    if actor_id is None:
        user = system_factcheck_user(db)
        actor_name = SYSTEM_ACTOR
    else:
        user = db.get(User, actor_id)
        if user is None:
            user = system_factcheck_user(db)
            actor_name = SYSTEM_ACTOR
    notice_source = _notice_source(db, source, notice.get("response_id"), notice_meta)
    payload = type("Payload", (), {})()
    payload.subject_type = "source"
    payload.subject_id = source.id
    payload.kind = "retraction"
    payload.reason = (
        f"{notice.get('detail') or 'A retraction was recorded by the automated check.'} "
        f"Provenance: automated check."
    ).strip()
    payload.source_id = notice_source.id
    try:
        record_upstream_invalidation(db, user, payload, actor=actor_name)
    except LibraryError as exc:
        notice["detail"] = f"{notice.get('detail', '')} Cascade was not applied: {exc.detail}".strip()


def _claim_ids(db: Session, source_id: int) -> set[int]:
    rows = (
        db.query(ClaimEvidence.claim_id)
        .join(Citation, Citation.id == ClaimEvidence.citation_id)
        .filter(Citation.source_id == source_id)
        .all()
    )
    return {row[0] for row in rows}


def _notice_source(db: Session, source: Source, response_id: str | None, notice_meta: dict | None) -> Source:
    from datetime import datetime

    doi = response_id if response_id and str(response_id).startswith("10.") and response_id != extract_doi(source.url, source.document_reference) else None
    meta = notice_meta or {}
    if doi and meta.get("title"):
        url = f"https://doi.org/{doi}"
        existing = db.query(Source).filter(Source.url == url).one_or_none()
        if existing is not None:
            return existing
        year = meta.get("year")
        notice = Source(
            title=meta["title"][:500],
            url=url,
            document_reference=doi,
            publisher=(meta.get("journal") or None),
            author=(meta.get("author") or None),
            publication_date=datetime(int(year), 1, 1) if year else None,
            source_type=source.source_type,
        )
    else:
        reference = f"retraction-check:{source.id}:{response_id or 'recorded'}"
        existing = db.query(Source).filter(Source.document_reference == reference).one_or_none()
        if existing is not None:
            return existing
        notice = Source(
            title=meta.get("title") or f"Retraction recorded for source {source.id}",
            url=None,
            document_reference=reference,
            publisher=(meta.get("journal") or None),
            author=(meta.get("author") or None),
            source_type=source.source_type,
        )
    db.add(notice)
    db.flush()
    return notice


def _collect_drafts(client, source: Source, excerpts: list[tuple[int, str]]) -> tuple[list[dict], dict | None]:
    """Network only. The caller must not be holding a database write transaction."""
    entered = _entered(source)
    doi = extract_doi(source.url, source.document_reference)
    pmid = extract_pmid(source.url, source.document_reference)
    drafts: list[dict] = []
    if doi:
        drafts.extend(crossref_checks(client, doi, entered))
    if pmid:
        drafts.extend(pubmed_checks(client, pmid, entered))
    if not doi and not pmid:
        if not source.url:
            drafts.extend(openalex_checks(client, source.title, source.author))
        document = extract_federal_register(source.url, source.document_reference)
        if document:
            drafts.append(federal_register_check(client, document))
        package = extract_govinfo(source.url, source.document_reference)
        if package:
            drafts.append(govinfo_check(client, package))
        opinion = extract_opinion(source.url, source.document_reference)
        if opinion:
            drafts.append(courtlistener_check(client, opinion))
    body = b""
    content_type = ""
    http_status = None
    if source.url:
        fetched, body, content_type = url_check(client, source.url)
        drafts.append(fetched)
        http_status = fetched.get("http_status")
        drafts.append(wayback_check(client, source.url))
        saved = save_page_check(client, source.url)
        if saved is not None:
            drafts.append(saved)
    for citation_id, excerpt in excerpts:
        drafts.append(quote_checks(excerpt, citation_id, body, content_type, http_status))
    notice_meta = None
    retraction = next((draft for draft in drafts if draft.get("result") == "retracted" and str(draft.get("response_id") or "").startswith("10.")), None)
    if retraction is not None:
        notice_meta = crossref_record(client, str(retraction["response_id"]))
    return drafts, notice_meta


def run_source_checks(db: Session, source_id: int, transport=None, actor_id: int | None = None) -> list[SourceCheck]:
    source = db.get(Source, source_id)
    if source is None:
        return []
    excerpts = [
        (citation.id, citation.excerpt)
        for citation in db.query(Citation).filter(Citation.source_id == source.id).all()
        if citation.excerpt
    ]
    db.commit()
    client = transport or get_transport()
    drafts, notice_meta = _collect_drafts(client, source, excerpts)
    source = db.get(Source, source_id)
    if source is None:
        return []
    _apply_retraction(db, source, drafts, actor_id, notice_meta)
    _apply_archive(source, drafts)
    rows = _persist(db, source.id, drafts)
    _flag_claims(db, source.id)
    from app.core.database import commit_with_retry

    commit_with_retry(db)
    return rows


def _flag_claims(db: Session, source_id: int) -> None:
    from app.models.claim import Claim

    for claim_id in _claim_ids(db, source_id):
        claim = db.get(Claim, claim_id)
        if claim is not None:
            from app.services.claim_confidence import assess_claim

            assess_claim(db, claim.id)


def run_claim_checks(db: Session, claim_id: int, transport=None, actor_id: int | None = None) -> list[SourceCheck]:
    from app.models.claim import Claim
    from app.services.scope_review import review_claim_scope

    claim = db.get(Claim, claim_id)
    if claim is None:
        return []
    claim_body = claim.body
    links = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == claim_id).all()
    source_ids = set()
    urls = []
    for link in links:
        citation = db.get(Citation, link.citation_id)
        if citation is None:
            continue
        source_ids.add(citation.source_id)
        source = db.get(Source, citation.source_id)
        if source is not None and source.url:
            urls.append(source.url)
    db.commit()
    client = transport or get_transport()
    rows: list[SourceCheck] = []
    for source_id in source_ids:
        rows.extend(run_source_checks(db, source_id, transport=client, actor_id=actor_id))
    text = ""
    for url in urls:
        _fetched, body, content_type = url_check(client, url)
        extracted = extract_text(body, content_type) or ""
        if len(extracted) > len(text):
            text = extracted
    related = openalex_related(client, claim_body, claim_id) + pubmed_related(client, claim_body, claim_id)
    model = llm_check(client, claim_body, text, claim_id)
    drafts = list(related)
    if model is not None:
        drafts.append(model)
    rows.extend(_persist(db, None, drafts))
    claim = db.get(Claim, claim_id)
    if claim is not None:
        review_claim_scope(db, claim)
        from app.services.claim_confidence import assess_claim

        assess_claim(db, claim.id)
    from app.core.database import commit_with_retry

    commit_with_retry(db)
    return rows


def process_verification_job(job_id: int, transport=None) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.get(VerificationJob, job_id)
        if job is None or job.status not in {"queued", "running"}:
            return
        job.status = "running"
        job.attempt_count += 1
        job.claimed_at = utcnow()
        db.commit()
        try:
            if job.subject_type == "claim":
                run_claim_checks(db, job.subject_id, transport=transport, actor_id=job.requested_by_user_id)
            else:
                run_source_checks(db, job.subject_id, transport=transport, actor_id=job.requested_by_user_id)
            job = db.get(VerificationJob, job_id)
            if job is not None:
                job.status = "completed"
                job.completed_at = utcnow()
                job.error_message = None
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(VerificationJob, job_id)
            if job is not None:
                job.status = "check_failed"
                job.error_message = str(exc)[:2000]
                db.commit()
    finally:
        db.close()
