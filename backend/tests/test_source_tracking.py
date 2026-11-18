from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_source_accepts_document_reference_and_stays_unverified():
    missing = client.post("/sources", json={"title": "Untitled locator", "source_type": "government_record"})
    assert missing.status_code == 422

    source = client.post(
        "/sources",
        json={
            "title": "Hearing transcript",
            "document_reference": "S. Hrg. 117-20, p. 14",
            "publisher": "U.S. Senate",
            "source_type": "government_record",
        },
    )
    assert source.status_code == 201, source.text
    body = source.json()
    assert body["url"] is None
    assert body["document_reference"] == "S. Hrg. 117-20, p. 14"
    assert body["verification_status"] == "unverified"
    assert body["archive_url"] is None
    assert body["archived_at"] is None

    blocked = client.post(
        "/sources",
        json={
            "title": "Client-verified record",
            "url": "https://example.gov/client-verified",
            "verification_status": "verified",
            "archive_url": "https://web.archive.org/web/example",
        },
    )
    assert blocked.status_code == 422


def test_evidence_link_requires_the_claim_it_supports():
    debate = client.post(
        "/debates",
        json={"title": "Locator debate", "fixed_question": "Does the transcript support the finding?"},
    ).json()
    claim = client.post(
        f"/debates/{debate['id']}/claims",
        json={"body": "The transcript records the finding.", "claim_type": "factual"},
    ).json()
    source = client.post(
        "/sources",
        json={"title": "Transcript", "document_reference": "S. Hrg. 117-20", "source_type": "primary_law"},
    ).json()
    citation = client.post("/citations", json={"source_id": source["id"], "locator": "p. 14"}).json()

    missing = client.post(
        f"/claims/{claim['id']}/evidence",
        json={"citation_id": citation["id"], "stance": "supports"},
    )
    assert missing.status_code == 422

    linked = client.post(
        f"/claims/{claim['id']}/evidence",
        json={
            "citation_id": citation["id"],
            "stance": "supports",
            "claim_supported": "The witness stated the finding on page 14.",
        },
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["claim_supported"] == "The witness stated the finding on page 14."

    account = client.post(
        "/auth/register",
        json={"email": "archivist@example.com", "display_name": "Archivist", "password": "verysecure123"},
    ).json()
    archived = client.post(
        "/verification-events",
        headers={"Authorization": f"Bearer {account['access_token']}"},
        json={
            "subject_type": "source",
            "subject_id": source["id"],
            "result_status": "archived",
            "method": "Captured a snapshot of the hearing PDF",
            "archive_url": "https://web.archive.org/web/2024/https://example.gov/hearing.pdf",
            "snapshot_hash": "sha256:hearing",
        },
    )
    assert archived.status_code == 201, archived.text
    stored = client.get(f"/sources/{source['id']}").json()
    assert stored["verification_status"] == "archived"
    assert stored["archive_url"].endswith("hearing.pdf")
    assert stored["archived_at"] is not None
