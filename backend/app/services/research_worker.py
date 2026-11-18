import argparse
import socket
import threading
import time
from datetime import datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.knowledge import ResearchJob, ResearchJobEvent, ResearchJobStatus

_STEPS = [
    (10, "Planning research"),
    (30, "Searching registered sources"),
    (55, "Comparing claims"),
    (80, "Preparing evidence summary"),
    (100, "Completed"),
]


def claim_next_job(worker_id: str) -> int | None:
    """Atomically claim one queued job. PostgreSQL uses SKIP LOCKED for multi-worker safety."""
    db = SessionLocal()
    try:
        statement = (
            select(ResearchJob)
            .where(ResearchJob.status == ResearchJobStatus.queued)
            .order_by(ResearchJob.created_at, ResearchJob.id)
            .limit(1)
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        job = db.execute(statement).scalar_one_or_none()
        if not job:
            return None
        job.status = ResearchJobStatus.running
        job.current_step = "Claimed by worker"
        job.claimed_at = datetime.utcnow()
        job.worker_id = worker_id
        job.attempt_count += 1
        db.add(ResearchJobEvent(
            job_id=job.id,
            progress_percent=job.progress_percent,
            step=job.current_step,
            message=f"Claimed by {worker_id}",
        ))
        db.commit()
        return job.id
    finally:
        db.close()


def process_job(job_id: int, delay: float = 0.03) -> None:
    for percent, step in _STEPS:
        if delay:
            time.sleep(delay)
        db = SessionLocal()
        try:
            job = db.get(ResearchJob, job_id)
            if not job or job.status == ResearchJobStatus.cancelled:
                return
            job.progress_percent = percent
            job.current_step = step
            job.status = ResearchJobStatus.completed if percent == 100 else ResearchJobStatus.running
            if percent == 100:
                job.result_summary = "Research workflow completed. Review linked sources, matches, and contradiction candidates."
                job.completed_at = datetime.utcnow()
            db.add(ResearchJobEvent(job_id=job.id, progress_percent=percent, step=step, message=step))
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ResearchJob, job_id)
            if job:
                job.error_message = str(exc)[:2000]
                if job.attempt_count >= settings.worker_max_attempts:
                    job.status = ResearchJobStatus.failed
                    job.completed_at = datetime.utcnow()
                else:
                    job.status = ResearchJobStatus.queued
                    job.worker_id = None
                    job.claimed_at = None
                db.commit()
            raise
        finally:
            db.close()


def run_worker(once: bool = False, poll_seconds: float | None = None) -> None:
    worker_id = f"{socket.gethostname()}:{__import__('os').getpid()}"
    interval = settings.worker_poll_seconds if poll_seconds is None else poll_seconds
    while True:
        job_id = claim_next_job(worker_id)
        if job_id is not None:
            process_job(job_id)
        elif once:
            return
        else:
            time.sleep(interval)
        if once:
            return


def enqueue_research_job(job_id: int) -> None:
    """Local convenience only; production leaves the row for the separate durable worker."""
    if settings.app_env.lower() != "production":
        threading.Thread(
            target=process_job,
            args=(job_id,),
            daemon=True,
            name=f"epic-local-research-{job_id}",
        ).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="EPIC durable research worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit")
    parser.add_argument("--poll-seconds", type=float, default=None)
    args = parser.parse_args()
    run_worker(once=args.once, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
