import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.database import SessionLocal
from app.main import app
from app.models.auth import AuthSession
from app.models.knowledge import ResearchJob, ResearchJobStatus
from app.services.research_worker import claim_next_job, process_job

client = TestClient(app)


def test_production_configuration_rejects_unsafe_defaults():
    with pytest.raises(ValidationError):
        Settings(app_env="production")


def test_list_settings_accept_csv_and_json():
    csv_settings = Settings(
        allowed_origins="http://localhost:8000, http://127.0.0.1:8000",
        trusted_hosts="localhost,127.0.0.1",
    )
    assert csv_settings.allowed_origins == ["http://localhost:8000", "http://127.0.0.1:8000"]
    assert csv_settings.trusted_hosts == ["localhost", "127.0.0.1"]
    json_settings = Settings(
        allowed_origins='["http://testserver"]',
        trusted_hosts='["testserver", "localhost"]',
    )
    assert json_settings.allowed_origins == ["http://testserver"]
    assert json_settings.trusted_hosts == ["testserver", "localhost"]


def test_session_lifetime_follows_session_hours():
    previous = settings.session_hours
    settings.session_hours = 2
    try:
        created = client.post(
            "/auth/register",
            json={"email": "session-hours@example.com", "display_name": "Session", "password": "verysecure123"},
        )
        assert created.status_code == 201, created.text
        with SessionLocal() as db:
            session = db.query(AuthSession).filter(AuthSession.user_id == created.json()["user"]["id"]).one()
            lifetime = session.expires_at - session.created_at
        assert abs(lifetime.total_seconds() - 2 * 60 * 60) < 5
    finally:
        settings.session_hours = previous


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
