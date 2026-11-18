from fastapi.testclient import TestClient

from app.main import app

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
    assert source.json()["quality_score"] == 0.95

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
    assert summary.json()["citation_requirement_met"] is True
    assert summary.json()["supports_score"] == 0.76
