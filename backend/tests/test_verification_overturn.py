from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth(email: str) -> dict:
    account = client.post(
        "/auth/register",
        json={"email": email, "display_name": "Reviewer", "password": "verysecure123"},
    )
    assert account.status_code == 201, account.text
    return {"Authorization": f"Bearer {account.json()['access_token']}", "user": account.json()["user"]}


def test_upheld_challenge_overturns_verified_claim_and_mistake_relabels_history():
    headers = _auth("overturn@example.com")
    debate = client.post(
        "/debates",
        json={"title": "Overturn debate", "fixed_question": "Did the record establish the hour count?"},
    ).json()
    claim = client.post(
        f"/debates/{debate['id']}/claims",
        json={"body": "The report records 12 hours of storage.", "claim_type": "factual"},
    ).json()
    participant = client.post(
        f"/debates/{debate['id']}/participants",
        json={"display_name": "Challenger", "role": "debater", "side": "negative"},
    ).json()
    source = client.post(
        "/sources",
        json={"title": "Agency report", "url": "https://example.gov/hours-overturn", "source_type": "government_record"},
    ).json()
    from app.core.database import SessionLocal
    from app.models.auth import User, UserRole
    with SessionLocal() as db:
        user = db.get(User, headers["user"]["id"])
        user.role = UserRole.moderator
        db.commit()
    reviewed = client.post(
        f"/sources/{source['id']}/source-type-review",
        headers={"Authorization": headers["Authorization"]},
        json={"note": "The published type matches the document."},
    )
    assert reviewed.status_code == 200, reviewed.text
    citation = client.post("/citations", json={"source_id": source["id"], "locator": "p. 4"}).json()
    link = client.post(
        f"/claims/{claim['id']}/evidence",
        json={
            "citation_id": citation["id"],
            "stance": "supports",
            "claim_supported": "The report records 12 hours of storage.",
        },
    ).json()
    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": "Overturn dossier", "question": "Did the record establish the hour count?"},
    ).json()
    knowledge = client.post(
        f"/knowledge/dossiers/{dossier['id']}/claims",
        json={"body": "The report records 12 hours of storage.", "originating_claim_id": claim["id"]},
    ).json()
    event = client.post(
        "/verification-events",
        headers={"Authorization": headers["Authorization"]},
        json={
            "subject_type": "knowledge_claim",
            "subject_id": knowledge["id"],
            "result_status": "verified",
            "method": "Compared page 4 with the archive snapshot",
            "snapshot_hash": "sha256:hours",
        },
    )
    assert event.status_code == 201, event.text
    challenge = client.post(
        f"/claim-evidence/{link['id']}/challenges",
        json={"challenger_id": participant["id"], "reason": "The footnote limits the 12 hours to one plant."},
    ).json()
    resolved = client.patch(
        f"/challenges/{challenge['id']}",
        headers={"Authorization": headers["Authorization"]},
        json={"status": "upheld", "response": "The limitation changes the claim."},
    )
    assert resolved.status_code == 200, resolved.text
    listed = client.get(f"/knowledge/dossiers/{dossier['id']}/claims").json()
    row = next(item for item in listed if item["id"] == knowledge["id"])
    assert row["status"] == "unverified"
    assert row["confidence_score"] is None
    note = row["status_history"][-1]["note"]
    assert f"verification event {event.json()['id']}" in note
    assert "Previously verified on" in note
    assert "invalidated:" not in note
    assert row["corrections"][-1]["kind"] == "verification_overturned"

    mistake = client.post(
        f"/verification-events/{event.json()['id']}/mistake",
        headers={"Authorization": headers["Authorization"]},
        json={"reason": "The snapshot was of a draft, not the issued report."},
    )
    assert mistake.status_code == 200, mistake.text
    listed = client.get(f"/knowledge/dossiers/{dossier['id']}/claims").json()
    row = next(item for item in listed if item["id"] == knowledge["id"])
    updated = " ".join(item["note"] for item in row["status_history"])
    assert "invalidated:" in updated
    assert "not a legitimate past verification" in updated
    assert row["status"] == "unverified"
