from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole

client = TestClient(app)


def test_claim_evidence_workflow():
    debate = client.post(
        "/debates",
        json={"title": "Test", "fixed_question": "Does the evidence support the claim?"},
    )
    assert debate.status_code == 201

    claim = client.post(
        f"/debates/{debate.json()['id']}/claims",
        json={"body": "The available evidence supports the claim.", "claim_type": "factual"},
    )
    assert claim.status_code == 201

    source = client.post(
        "/sources",
        json={
            "title": "Official record",
            "url": "https://example.gov/record",
            "publisher": "Example Agency",
            "source_type": "government_record",
        },
    )
    assert source.status_code == 201
    assert source.json()["quality_score"] == 0.0
    assert source.json()["source_type_reviewed"] is False
    assert "unverified" in source.json()["quality_rationale"]

    citation = client.post(
        "/citations",
        json={"source_id": source.json()["id"], "locator": "p. 4", "excerpt": "Relevant evidence."},
    )
    assert citation.status_code == 201

    link = client.post(
        f"/claims/{claim.json()['id']}/evidence",
        json={
            "citation_id": citation.json()["id"],
            "stance": "supports",
            "relevance_score": 0.8,
            "claim_supported": "The available evidence supports the claim.",
        },
    )
    assert link.status_code == 201

    summary = client.get(f"/claims/{claim.json()['id']}/evidence-summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["citation_requirement_met"] is True
    assert "net_evidence_score" not in body
    assert body["items"][0]["declared_source_type"] == "government_record"
    assert body["items"][0]["source_type_reviewed"] is False
    assert body["items"][0]["effective_tier"] == "unknown"
    assert body["strongest_effective_tier"] == "unknown"
    assert body["items"][0]["claim_supported"] == "The available evidence supports the claim."


def test_source_type_stays_unverified_until_a_reviewer_confirms_it():
    source = client.post(
        "/sources",
        json={
            "title": "Agency table",
            "url": "https://example.gov/table",
            "publisher": "Example Agency",
            "source_type": "official_data",
        },
    )
    assert source.status_code == 201
    assert source.json()["source_type_reviewed"] is False
    account = client.post(
        "/auth/register",
        json={"email": "source-reviewer@example.com", "display_name": "Reviewer", "password": "verysecure123"},
    ).json()
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    denied = client.post(
        f"/sources/{source.json()['id']}/source-type-review",
        headers=headers,
        json={"note": "I have not been granted review permission."},
    )
    assert denied.status_code == 403
    with SessionLocal() as db:
        user = db.get(User, account["user"]["id"])
        user.role = UserRole.moderator
        db.commit()
    reviewed = client.post(
        f"/sources/{source.json()['id']}/source-type-review",
        headers=headers,
        json={"note": "The table is on the agency's official data page."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["source_type_reviewed"] is True
    assert reviewed.json()["source_type_reviewed_by_user_id"] == account["user"]["id"]
    assert reviewed.json()["quality_score"] == 0.0
