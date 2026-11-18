import pytest
from pydantic import ValidationError
from app.core.config import Settings
from app.core.database import SessionLocal
from app.models.knowledge import ResearchJob, ResearchJobStatus
from app.services.research_worker import claim_next_job, process_job


def test_production_configuration_rejects_unsafe_defaults():
    with pytest.raises(ValidationError):
        Settings(app_env="production")


def test_database_backed_worker_claims_and_completes_job():
    db = SessionLocal()
    job = ResearchJob(query="durable worker test")
    db.add(job); db.commit(); job_id = job.id; db.close()

    claimed = claim_next_job("test-worker")
    assert claimed == job_id
    process_job(job_id, delay=0)

    db = SessionLocal(); completed = db.get(ResearchJob, job_id)
    assert completed.status == ResearchJobStatus.not_implemented
    assert completed.progress_percent == 0
    assert completed.result_summary is None
    assert "not implemented" in completed.error_message
    assert completed.worker_id == "test-worker"
    assert completed.attempt_count == 1
    db.close()
