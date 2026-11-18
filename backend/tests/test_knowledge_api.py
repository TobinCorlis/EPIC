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

    progress = client.patch(
        f"/knowledge/jobs/{job_id}",
        json={"progress_percent": 45, "current_step": "Reviewing sources", "message": "Three sources screened"},
    )
    assert progress.status_code == 200
    assert progress.json()["status"] == "running"

    completed = client.patch(
        f"/knowledge/jobs/{job_id}",
        json={
            "progress_percent": 100,
            "current_step": "Complete",
            "message": "Research package ready",
            "result_summary": "Five official and peer-reviewed sources retained.",
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    events = client.get(f"/knowledge/jobs/{job_id}/events")
    assert events.status_code == 200
    assert [event["progress_percent"] for event in events.json()] == [0, 45, 100]


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


def test_research_progress_cannot_move_backward():
    job = client.post("/knowledge/jobs", json={"query": "Research a stable historical question"})
    assert job.status_code == 201
    job_id = job.json()["id"]
    assert client.patch(
        f"/knowledge/jobs/{job_id}",
        json={"progress_percent": 60, "current_step": "Extracting claims"},
    ).status_code == 200
    backwards = client.patch(
        f"/knowledge/jobs/{job_id}",
        json={"progress_percent": 20, "current_step": "Searching"},
    )
    assert backwards.status_code == 409
