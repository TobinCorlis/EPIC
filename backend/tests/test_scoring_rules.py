from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole

client = TestClient(app)


def _moderator(email: str) -> dict:
    account = client.post(
        "/auth/register",
        json={"email": email, "display_name": "Score Reviewer", "password": "verysecure123"},
    )
    assert account.status_code == 201, account.text
    with SessionLocal() as db:
        user = db.get(User, account.json()["user"]["id"])
        user.role = UserRole.moderator
        db.commit()
    return {"Authorization": f"Bearer {account.json()['access_token']}"}


def _debate_claim(body: str) -> dict:
    debate = client.post(
        "/debates",
        json={"title": body[:40], "fixed_question": "Does the recorded evidence answer the question?"},
    ).json()
    claim = client.post(f"/debates/{debate['id']}/claims", json={"body": body, "claim_type": "factual"})
    assert claim.status_code == 201, claim.text
    return claim.json()


def _source(headers, title: str, url: str, source_type: str = "unknown"):
    created = client.post(
        "/sources",
        headers=headers,
        json={"title": title, "url": url, "publisher": title, "source_type": source_type},
    )
    assert created.status_code == 201, created.text
    return created.json()


def _mark(headers, source_id: int, status: str):
    reviewed = client.post(
        f"/sources/{source_id}/record-review",
        headers=headers,
        json={"status": status, "note": "Checked the citation against the stored record."},
    )
    assert reviewed.status_code == 200, reviewed.text


def _review_tier(headers, source_id: int):
    reviewed = client.post(
        f"/sources/{source_id}/source-type-review",
        headers=headers,
        json={"note": "The published type matches the document."},
    )
    assert reviewed.status_code == 200, reviewed.text


def _link(claim_id: int, source_id: int, stance: str = "supports"):
    citation = client.post("/citations", json={"source_id": source_id, "locator": "p. 1"}).json()
    linked = client.post(
        f"/claims/{claim_id}/evidence",
        json={"citation_id": citation["id"], "stance": stance, "claim_supported": "The recorded measurement."},
    )
    assert linked.status_code == 201, linked.text


def _summary(claim_id: int) -> dict:
    summary = client.get(f"/claims/{claim_id}/evidence-summary")
    assert summary.status_code == 200, summary.text
    return summary.json()["confidence"]


def test_no_supporting_evidence_is_unsupported_at_zero():
    claim = _debate_claim("No source has been attached.")
    confidence = _summary(claim["id"])
    assert confidence["confidence_score"] == 0
    assert confidence["label"] == "Unsupported"
    assert confidence["scale"] == "0–1"
    assert confidence["label"] != "Unknown – not yet rated"
    assert confidence["automated_source_check"] == "not_implemented"


def test_missing_citation_is_recorded_as_no_record_found():
    headers = _moderator("missing-record@example.com")
    claim = _debate_claim("A paper is cited, but no record of it was found.")
    source = _source(headers, "Unlocated paper", "https://example.edu/missing-paper")
    _mark(headers, source["id"], "no_record_found")
    _link(claim["id"], source["id"])
    confidence = _summary(claim["id"])
    assert confidence["confidence_score"] == 0
    assert confidence["label"] == "Unsupported"
    assert confidence["cited_source_note"] == "cited source: no record found"
    assert "cited source: no record found" in confidence["factors"][0]["detail"]


def test_found_but_unreviewed_evidence_is_not_yet_rated():
    headers = _moderator("unrated@example.com")
    claim = _debate_claim("The agency table is filed and not yet rated.")
    source = _source(headers, "Filed agency table", "https://example.gov/filed-table", "government_record")
    _mark(headers, source["id"], "found")
    _link(claim["id"], source["id"])
    confidence = _summary(claim["id"])
    assert confidence["confidence_score"] is None
    assert confidence["label"] == "Unknown – not yet rated"
    assert confidence["cited_source_note"] is None


def test_supported_without_reviewed_tier_is_downgraded_and_verified_is_blocked():
    headers = _moderator("downgrade@example.com")
    claim = _debate_claim("The status was marked supported before the tier was reviewed.")
    source = _source(headers, "Unreviewed table", "https://example.gov/unreviewed-table", "government_record")
    _link(claim["id"], source["id"])
    entry = client.post(
        "/library/entries",
        headers=headers,
        json={
            "question": "Was the unreviewed table enough to support the claim?",
            "direct_answer": "yes",
            "status": "supported",
            "facts": "A table was cited.",
            "interpretation": "The citation was treated as support.",
            "uncertainty": "The tier has not been reviewed.",
            "supporting_claim_ids": [claim["id"]],
            "covered_points": ["A table was cited."],
            "change_log": "Tried to mark the entry supported.",
        },
    )
    assert entry.status_code == 201, entry.text
    stored = entry.json()
    assert stored["current_version"]["status"] == "unresolved"
    assert stored["needs_review"] is True
    assert "reviewed tier" in stored["current_version"]["change_log"]
    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": "Downgrade dossier", "question": "Was the unreviewed table enough?"},
    ).json()
    knowledge = client.post(
        f"/knowledge/dossiers/{dossier['id']}/claims",
        json={"body": "The unreviewed table settles it.", "originating_claim_id": claim["id"]},
    ).json()
    blocked = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "knowledge_claim",
            "subject_id": knowledge["id"],
            "result_status": "verified",
            "method": "Read the table",
            "archive_url": "https://example.gov/archive/unreviewed",
        },
    )
    assert blocked.status_code == 409, blocked.text
    listed = client.get(f"/knowledge/dossiers/{dossier['id']}/claims").json()
    assert listed[0]["status"] == "unverified"
    flagged = client.get(f"/debates/{claim['debate_id']}/claims").json()[0]
    assert flagged["needs_review"] is True


def test_fabricated_lake_laser_is_refuted_by_geodetic_evidence():
    headers = _moderator("laser@example.com")
    claim = _debate_claim("A lake laser experiment raised the shoreline.")
    laser = _source(headers, "Lake laser experiment", "https://example.edu/lake-laser")
    _mark(headers, laser["id"], "no_record_found")
    geodetic = _source(headers, "National geodetic survey", "https://example.gov/geodetic-shoreline", "official_data")
    _review_tier(headers, geodetic["id"])
    _link(claim["id"], laser["id"], "supports")
    _link(claim["id"], geodetic["id"], "contradicts")
    confidence = _summary(claim["id"])
    assert confidence["label"] == "Refuted"
    assert confidence["confidence_score"] == 0
    assert confidence["cited_source_note"] == "cited source: no record found"
    assert any(source["title"] == "National geodetic survey" for source in confidence["contradicting_sources"])
    assert "not_implemented" in confidence["automated_source_check"]


def test_weaker_contradiction_does_not_refute_stronger_reviewed_support():
    headers = _moderator("weaker@example.com")
    claim = _debate_claim("The agency figure stands despite a later blog.")
    government = _source(headers, "Agency figure", "https://example.gov/agency-figure", "government_record")
    blog = _source(headers, "Later blog", "https://blog.example/later-blog", "user_generated")
    _review_tier(headers, government["id"])
    _review_tier(headers, blog["id"])
    _link(claim["id"], government["id"], "supports")
    _link(claim["id"], blog["id"], "contradicts")
    confidence = _summary(claim["id"])
    assert confidence["label"] == "Rated"
    assert confidence["confidence_score"] > 0
    assert confidence["contradicting_sources"] == []
    assert confidence["factors"][0]["value"] == round(7 / 8, 2)
