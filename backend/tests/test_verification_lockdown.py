from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def register(email: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"email": email, "display_name": "Reviewer", "password": "verysecure123"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_client_cannot_create_a_verified_knowledge_claim():
    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": "Verification lockdown", "question": "Is the claim verified?"},
    )
    assert dossier.status_code == 201
    dossier_id = dossier.json()["id"]

    rejected = client.post(
        f"/knowledge/dossiers/{dossier_id}/claims",
        json={
            "body": "An unsourced statement presented as verified.",
            "status": "verified",
            "confidence_score": 1.0,
        },
    )
    assert rejected.status_code == 422

    created = client.post(
        f"/knowledge/dossiers/{dossier_id}/claims",
        json={"body": "An unsourced statement presented as verified."},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "unverified"
    assert created.json()["confidence_score"] == 0.0


def test_verified_and_archived_require_a_recorded_event():
    account = register("verifier@example.com")
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    debate = client.post(
        "/debates",
        json={"title": "Verification debate", "fixed_question": "Does the record establish the finding?"},
    ).json()
    participant = client.post(
        f"/debates/{debate['id']}/participants",
        json={"display_name": "Debater", "role": "debater", "side": "affirmative"},
    ).json()
    node = client.post(
        f"/debates/{debate['id']}/arguments",
        json={"participant_id": participant["id"], "node_type": "premise", "body": "The record is the finding."},
    )
    assert node.status_code == 201
    assert node.json()["verification_status"] == "unverified"
    node_id = node.json()["id"]

    for status_name in ("verified", "archived"):
        blocked = client.patch(
            f"/arguments/{node_id}/verification",
            json={"verification_status": status_name},
        )
        assert blocked.status_code == 422

    anonymous = client.post(
        "/verification-events",
        json={
            "subject_type": "argument_node",
            "subject_id": node_id,
            "result_status": "verified",
            "method": "Compared the record to an archive snapshot",
            "archive_url": "https://web.archive.org/web/example",
        },
    )
    assert anonymous.status_code == 401

    missing_evidence = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "argument_node",
            "subject_id": node_id,
            "result_status": "verified",
            "method": "Compared the record to an archive snapshot",
        },
    )
    assert missing_evidence.status_code == 422

    recorded = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "argument_node",
            "subject_id": node_id,
            "result_status": "verified",
            "method": "Compared the record to an archive snapshot",
            "snapshot_hash": "sha256:abc123",
        },
    )
    assert recorded.status_code == 201, recorded.text
    body = recorded.json()
    assert body["actor_user_id"] == account["user"]["id"]
    assert body["method"].startswith("Compared")
    assert body["snapshot_hash"] == "sha256:abc123"
    assert body["created_at"]

    listed = client.get(
        "/verification-events",
        params={"subject_type": "argument_node", "subject_id": node_id},
    )
    assert listed.status_code == 200
    assert listed.json()[0]["result_status"] == "verified"
    current = client.get(f"/debates/{debate['id']}/arguments").json()
    assert current[0]["verification_status"] == "verified"

    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": "Archive status", "question": "Was the source archived?"},
    ).json()
    claim = client.post(
        f"/knowledge/dossiers/{dossier['id']}/claims",
        json={"body": "The hearing transcript is the record."},
    ).json()
    archived = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "knowledge_claim",
            "subject_id": claim["id"],
            "result_status": "archived",
            "method": "Saved an archive snapshot of the transcript",
            "archive_url": "https://web.archive.org/web/2020/https://example.gov/hearing",
        },
    )
    assert archived.status_code == 201, archived.text
    claims = client.get(f"/knowledge/dossiers/{dossier['id']}/claims").json()
    assert claims[0]["status"] == "archived"
    assert claims[0]["confidence_score"] == 0.0
