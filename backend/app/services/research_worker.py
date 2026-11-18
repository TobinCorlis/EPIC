import argparse
import socket
import threading
import time

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.knowledge import ResearchJob, ResearchJobEvent, ResearchJobStatus
from app.core.clock import utcnow

NOT_IMPLEMENTED_STEP = "Automated research is not implemented"
NOT_IMPLEMENTED_MESSAGE = (
    "Automated research is not implemented. No sources were searched and no claims were compared."
)


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
        job.claimed_at = utcnow()
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


def process_job(job_id: int, delay: float = 0.0) -> None:
    """Record that no automated research was performed.

    The delay argument is ignored. It remains so existing callers do not
    simulate work that this worker does not do.
    """
    del delay
    db = SessionLocal()
    try:
        job = db.get(ResearchJob, job_id)
        if not job or job.status == ResearchJobStatus.cancelled:
            return
        job.status = ResearchJobStatus.not_implemented
        job.progress_percent = 0
        job.current_step = NOT_IMPLEMENTED_STEP
        job.result_summary = None
        job.error_message = NOT_IMPLEMENTED_MESSAGE
        job.completed_at = None
        db.add(ResearchJobEvent(
            job_id=job.id,
            progress_percent=0,
            step=NOT_IMPLEMENTED_STEP,
            message=NOT_IMPLEMENTED_MESSAGE,
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(ResearchJob, job_id)
        if job and job.status != ResearchJobStatus.not_implemented:
            job.error_message = str(exc)[:2000]
            job.status = ResearchJobStatus.failed
            job.completed_at = None
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
