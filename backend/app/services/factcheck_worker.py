"""Database-backed worker for automated source checks.

    python -m app.services.factcheck_worker --once

Network failures stay on the check row as check_failed. The worker does not
mark a source verified.
"""
from __future__ import annotations

import argparse
import socket
from datetime import timedelta

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.evidence import Source
from app.models.factcheck import SourceCheck, VerificationJob
from app.services.factcheck.runner import enqueue_verification, process_verification_job


def claim_next_job(worker_id: str) -> int | None:
    db = SessionLocal()
    try:
        statement = (
            select(VerificationJob)
            .where(VerificationJob.status == "queued")
            .order_by(VerificationJob.created_at, VerificationJob.id)
            .limit(1)
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        job = db.execute(statement).scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.worker_id = worker_id
        job.claimed_at = utcnow()
        db.commit()
        return job.id
    finally:
        db.close()


def enqueue_due_rechecks(limit: int = 20) -> int:
    """Queue sources whose latest check is older than the recheck window."""
    db = SessionLocal()
    try:
        cutoff = utcnow() - timedelta(days=settings.factcheck_recheck_days)
        queued = 0
        for source in db.query(Source).order_by(Source.id).all():
            latest = (
                db.query(SourceCheck)
                .filter(SourceCheck.source_id == source.id)
                .order_by(SourceCheck.id.desc())
                .first()
            )
            if latest is not None and latest.created_at >= cutoff:
                continue
            already = (
                db.query(VerificationJob)
                .filter(
                    VerificationJob.subject_type == "source",
                    VerificationJob.subject_id == source.id,
                    VerificationJob.status == "queued",
                )
                .first()
            )
            if already is not None:
                continue
            enqueue_verification(db, "source", source.id, None)
            queued += 1
            if queued >= limit:
                break
        db.commit()
        return queued
    finally:
        db.close()


def run_worker(once: bool = False, poll_seconds: float | None = None, recheck: bool = True) -> None:
    import time

    worker_id = f"{socket.gethostname()}:{__import__('os').getpid()}"
    interval = settings.worker_poll_seconds if poll_seconds is None else poll_seconds
    while True:
        if recheck:
            enqueue_due_rechecks()
        job_id = claim_next_job(worker_id)
        if job_id is not None:
            process_verification_job(job_id)
        elif once:
            return
        else:
            time.sleep(interval)
        if once:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="EPIC source fact-check worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit")
    parser.add_argument("--poll-seconds", type=float, default=None)
    parser.add_argument("--no-recheck", action="store_true", help="Do not queue periodic re-checks")
    args = parser.parse_args()
    run_worker(once=args.once, poll_seconds=args.poll_seconds, recheck=not args.no_recheck)


if __name__ == "__main__":
    main()
