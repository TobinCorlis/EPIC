from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dossier_duplicate_matching_and_research_progress():
    dossier = client.post(
        "/knowledge/dossiers",
        json={
            "title": "Renewable Grid Reliability",
            "question": "Can a renewable-heavy grid remain reliable?",
            "summary": "Reusable evidence and claims for grid reliability debates.",
        },
    )
    assert dossier.status_code == 201
    dossier_id = dossier.json()["id"]

    first = client.post(
        f"/knowledge/dossiers/{dossier_id}/claims",
        json={"body": "Renewable-heavy grids can remain reliable with adequate storage and transmission."},
    )
    assert first.status_code == 201

    matches = client.post(
        f"/knowledge/dossiers/{dossier_id}/match-claim",
        json={"body": "With adequate storage and transmission, renewable-heavy grids can remain reliable."},
    )
    assert matches.status_code == 200
    assert matches.json()[0]["duplicate"] is True

    job = client.post(
        "/knowledge/jobs",
        json={"query": "Find official grid reliability studies", "dossier_id": dossier_id},
    )
    assert job.status_code == 201
    job_id = job.json()["id"]

    fabricated = client.patch(
        f"/knowledge/jobs/{job_id}",
        json={
            "progress_percent": 100,
            "current_step": "Complete",
            "message": "Research package ready",
            "result_summary": "Five official and peer-reviewed sources retained.",
            "status": "completed",
        },
    )
    assert fabricated.status_code == 401
    stored = client.get(f"/knowledge/jobs/{job_id}")
    assert stored.json()["status"] == "queued"
    assert stored.json()["result_summary"] is None
    from app.core.database import SessionLocal
    from app.models.knowledge import ResearchJob, ResearchJobStatus

    with SessionLocal() as db:
        row = db.get(ResearchJob, job_id)
        row.status = ResearchJobStatus.cancelled
        db.commit()


def test_contradiction_candidate_is_created_and_reviewable():
    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": "Policy Effect Test", "question": "Did the policy reduce reported incidents?"},
    )
    assert dossier.status_code == 201
    dossier_id = dossier.json()["id"]

    a = client.post(
        f"/knowledge/dossiers/{dossier_id}/claims",
        json={"body": "The policy reduced reported incidents in the county."},
    )
    b = client.post(
        f"/knowledge/dossiers/{dossier_id}/claims",
        json={"body": "The policy did not reduce reported incidents in the county."},
    )
    assert a.status_code == 201
    assert b.status_code == 201

    contradictions = client.get(f"/knowledge/dossiers/{dossier_id}/contradictions")
    assert contradictions.status_code == 200
    assert len(contradictions.json()) == 1
    contradiction_id = contradictions.json()[0]["id"]

    reviewed = client.patch(
        f"/knowledge/contradictions/{contradiction_id}",
        json={"status": "confirmed"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "confirmed"


def test_staff_cannot_fabricate_research_completion():
    account = client.post(
        "/auth/register",
        json={"email": "research-moderator@example.com", "display_name": "Research Mod", "password": "verysecure123"},
    )
    assert account.status_code == 201
    from app.core.database import SessionLocal
    from app.models.auth import User, UserRole

    with SessionLocal() as db:
        user = db.get(User, account.json()["user"]["id"])
        user.role = UserRole.moderator
        db.commit()
    headers = {"Authorization": f"Bearer {account.json()['access_token']}"}
    job = client.post("/knowledge/jobs", json={"query": "Research a stable historical question"})
    assert job.status_code == 201
    job_id = job.json()["id"]
    blocked = client.patch(
        f"/knowledge/jobs/{job_id}",
        headers=headers,
        json={
            "status": "completed",
            "progress_percent": 100,
            "current_step": "Complete",
            "result_summary": "Sources were not actually searched.",
        },
    )
    assert blocked.status_code == 409
    assert "not implemented" in blocked.json()["detail"]
    stored = client.get(f"/knowledge/jobs/{job_id}").json()
    assert stored["status"] == "queued"
    assert stored["result_summary"] is None

    cancelled = client.patch(
        f"/knowledge/jobs/{job_id}",
        headers=headers,
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["result_summary"] is None
