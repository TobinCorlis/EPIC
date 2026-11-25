from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole

client = TestClient(app)


def _claim(title: str, url: str):
    debate = client.post(
        "/debates",
        json={"title": title, "fixed_question": "Does the record support the hour count?"},
    ).json()
    claim = client.post(
        f"/debates/{debate['id']}/claims",
        json={"body": f"The record supports {title}.", "claim_type": "factual"},
    ).json()
    return debate, claim


def _source(title: str, url: str, source_type: str, publisher: str):
    return client.post(
        "/sources",
        json={"title": title, "url": url, "publisher": publisher, "source_type": source_type},
    ).json()


def _review(source_id: int, email: str):
    account = client.post(
        "/auth/register",
        json={"email": email, "display_name": "Reviewer", "password": "verysecure123"},
    ).json()
    with SessionLocal() as db:
        user = db.get(User, account["user"]["id"])
        user.role = UserRole.moderator
        db.commit()
    reviewed = client.post(
        f"/sources/{source_id}/source-type-review",
        headers={"Authorization": f"Bearer {account['access_token']}"},
        json={"note": "The published type matches the document."},
    )
    assert reviewed.status_code == 200, reviewed.text


def _link(claim_id: int, source_id: int, stance: str = "supports"):
    citation = client.post("/citations", json={"source_id": source_id, "locator": "p. 1"}).json()
    linked = client.post(
        f"/claims/{claim_id}/evidence",
        json={"citation_id": citation["id"], "stance": stance, "claim_supported": "The record states the measured result."},
    )
    assert linked.status_code == 201, linked.text


def test_confidence_uses_tier_not_volume_and_does_not_verify():
    _, government_claim = _claim("Government confidence", "gov")
    government = _source("Agency table", "https://example.gov/confidence-table", "government_record", "Example Agency")
    _review(government["id"], "confidence-mod@example.com")
    _link(government_claim["id"], government["id"])
    blogs_debate, blogs_claim = _claim("Blog confidence", "blogs")
    for index in range(6):
        blog = _source(f"Blog {index}", f"https://blog{index}.example/confidence", "user_generated", f"Blog {index}")
        _review(blog["id"], f"blog-mod-{index}@example.com")
        _link(blogs_claim["id"], blog["id"])
    government_summary = client.get(f"/claims/{government_claim['id']}/evidence-summary").json()
    blog_summary = client.get(f"/claims/{blogs_claim['id']}/evidence-summary").json()
    assert government_summary["confidence"]["confidence_score"] > blog_summary["confidence"]["confidence_score"]
    assert government_summary["confidence"]["automated_source_check"] == "not_checked"
    factors = {item["name"]: item["value"] for item in government_summary["confidence"]["factors"]}
    assert factors["track_record"] is None
    assert "unknown" in next(item["detail"] for item in government_summary["confidence"]["factors"] if item["name"] == "track_record")
    assert client.get(f"/debates/{blogs_debate['id']}/claims").json()[0]["on_topic"] is True
    record = client.get(f"/sources/{government['id']}/record").json()
    assert record["automated_source_check"] == "not_checked"
    assert record["found_false"] == 0
