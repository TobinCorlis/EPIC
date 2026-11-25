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


def kickoff(job_id: int) -> None:
    if not settings.factcheck_auto_run:
        return
    threading.Thread(
        target=process_verification_job,
        args=(job_id,),
        daemon=True,
        name=f"epic-factcheck-{job_id}",
    ).start()


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


def _apply_retraction(db: Session, source: Source, drafts: list[dict], actor_id: int | None) -> None:
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
        )
        .first()
    )
    if existing is not None or actor_id is None:
        if actor_id is None:
            notice["detail"] = (
                notice.get("detail", "")
                + " The upstream cascade was not applied because no actor was stored on the job."
            ).strip()
        return
    from app.models.auth import User
    from app.services.reference_library import LibraryError, record_upstream_invalidation

    user = db.get(User, actor_id)
    role = user.role.value if user is not None and hasattr(user.role, "value") else user.role if user is not None else None
    if user is None or role not in {"moderator", "administrator"}:
        notice["detail"] = (
            notice.get("detail", "")
            + " The upstream cascade waits for a moderator."
        ).strip()
        return
    notice_source = _notice_source(db, source, notice.get("response_id"))
    payload = type("Payload", (), {})()
    payload.subject_type = "source"
    payload.subject_id = source.id
    payload.kind = "retraction"
    payload.reason = notice.get("detail") or "A retraction was recorded by the automated check."
    payload.source_id = notice_source.id
    try:
        record_upstream_invalidation(db, user, payload)
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


def _notice_source(db: Session, source: Source, response_id: str | None) -> Source:
    doi = response_id if response_id and response_id.startswith("10.") and response_id != extract_doi(source.url, source.document_reference) else None
    if doi:
        url = f"https://doi.org/{doi}"
        existing = db.query(Source).filter(Source.url == url).one_or_none()
        if existing is not None:
            return existing
        notice = Source(
            title=f"Retraction notice {doi}",
            url=url,
            document_reference=doi,
            source_type=source.source_type,
        )
    else:
        reference = f"retraction-check:{source.id}:{response_id or 'recorded'}"
        existing = db.query(Source).filter(Source.document_reference == reference).one_or_none()
        if existing is not None:
            return existing
        notice = Source(
            title=f"Retraction recorded for source {source.id}",
            url=None,
            document_reference=reference,
            source_type=source.source_type,
        )
    db.add(notice)
    db.flush()
    return notice


def run_source_checks(db: Session, source_id: int, transport=None, actor_id: int | None = None) -> list[SourceCheck]:
    source = db.get(Source, source_id)
    if source is None:
        return []
    client = transport or get_transport()
    entered = _entered(source)
    doi = extract_doi(source.url, source.document_reference)
    pmid = extract_pmid(source.url, source.document_reference)
    drafts: list[dict] = []
    if doi:
        drafts.extend(crossref_checks(client, doi, entered))
    if pmid:
        drafts.extend(pubmed_checks(client, pmid, entered))
    if not doi and not pmid:
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
    citations = db.query(Citation).filter(Citation.source_id == source.id).all()
    for citation in citations:
        if citation.excerpt:
            drafts.append(quote_checks(citation.excerpt, citation.id, body, content_type, http_status))
    _apply_retraction(db, source, drafts, actor_id)
    _apply_archive(source, drafts)
    rows = _persist(db, source.id, drafts)
    _flag_claims(db, source.id)
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
    client = transport or get_transport()
    links = (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.claim_id == claim_id)
        .all()
    )
    rows: list[SourceCheck] = []
    source_ids = set()
    for link in links:
        citation = db.get(Citation, link.citation_id)
        if citation is None:
            continue
        source_ids.add(citation.source_id)
    for source_id in source_ids:
        rows.extend(run_source_checks(db, source_id, transport=client, actor_id=actor_id))
    text = ""
    for source_id in source_ids:
        source = db.get(Source, source_id)
        if source and source.url:
            fetched, body, content_type = url_check(client, source.url)
            extracted = extract_text(body, content_type) or ""
            if len(extracted) > len(text):
                text = extracted
            _persist(db, source_id, [fetched])
    related = openalex_related(client, claim.body, claim.id) + pubmed_related(client, claim.body, claim.id)
    rows.extend(_persist(db, None, related))
    model = llm_check(client, claim.body, text, claim.id)
    if model is not None:
        rows.extend(_persist(db, None, [model]))
    review_claim_scope(db, claim)
    from app.services.claim_confidence import assess_claim

    assess_claim(db, claim.id)
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
