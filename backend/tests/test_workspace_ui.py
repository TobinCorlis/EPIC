import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.cli import AdminBootstrapError, create_first_admin
from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole

client = TestClient(app)
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _contrast(color: str) -> float:
    red, green, blue = (int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)
    return 1.05 / (luminance + 0.05)


def test_workspace_markup_exposes_the_recorded_controls():
    page = (STATIC / "index.html").read_text()
    script = (STATIC / "app.js").read_text()
    styles = (STATIC / "styles.css").read_text()
    served = client.get("/")
    assert served.status_code == 200
    assert "Request re-evaluation" in script
    assert "re-evaluation pending" in script
    assert "Answer:" in script and "Status:" in script
    assert "Open entry" in script
    assert "Open library entry" in script
    assert "New points, not yet researched" in script
    assert "Configure room" in page
    assert "The debate owner, a moderator, or an administrator configures this room." in page
    assert 'aria-selected' in page
    assert "Confidence:" in script
    assert "unknown" in script
    assert "Status history" in script
    assert "not implemented" in script
    for needle in ("Request re-evaluation", "library-intro", "library-banner", "Configure room"):
        assert needle in served.text or needle in script
    match = re.search(r"\.library-intro\{[^}]*color:(#[0-9a-fA-F]{6})", styles)
    assert match, styles
    assert _contrast(match.group(1)) >= 4.5
    assert "font-size:16px" in styles.split(".library-intro{")[1].split("}")[0]


def test_local_email_is_accepted_by_the_admin_command_and_login():
    from app.core.email import normalize_email

    assert normalize_email("Admin@EPIC.local") == "admin@epic.local"
    registered = client.post(
        "/auth/register",
        json={"email": "member@epic.local", "display_name": "Local Member", "password": "verysecure123"},
    )
    assert registered.status_code == 201, registered.text
    login = client.post("/auth/login", json={"email": "member@epic.local", "password": "verysecure123"})
    assert login.status_code == 200, login.text
    rejected = client.post(
        "/auth/register",
        json={"email": "not-an-email", "display_name": "Nope", "password": "verysecure123"},
    )
    assert rejected.status_code == 422
    try:
        create_first_admin("also-not-an-email", "Nope", "verysecure123")
    except AdminBootstrapError as exc:
        assert "valid email" in str(exc).lower()
    else:
        raise AssertionError("The admin command accepted an address the login form rejects")
    with SessionLocal() as db:
        admin_exists = db.query(User).filter(User.role == UserRole.administrator).first() is not None
    if not admin_exists:
        created = create_first_admin("Admin@EPIC.local", "Local Admin", "verysecure123")
        assert created.email == "admin@epic.local"
        created_login = client.post("/auth/login", json={"email": "admin@epic.local", "password": "verysecure123"})
        assert created_login.status_code == 200, created_login.text


def test_evidence_and_library_reads_include_the_fields_the_page_shows():
    account = client.post(
        "/auth/register",
        json={"email": "ui-reader@example.com", "display_name": "Reader", "password": "verysecure123"},
    )
    assert account.status_code == 201, account.text
    headers = {"Authorization": f"Bearer {account.json()['access_token']}"}
    debate = client.post(
        "/debates",
        headers=headers,
        json={
            "title": "UI scope debate",
            "fixed_question": "Did the city rate change?",
            "question_population": "city residents",
        },
    ).json()
    claim = client.post(
        f"/debates/{debate['id']}/claims",
        headers=headers,
        json={"body": "The national rate changed for everyone.", "claim_type": "factual", "scope_population": "national residents"},
    ).json()
    source = client.post(
        "/sources",
        headers=headers,
        json={
            "title": "City table",
            "url": "https://example.gov/ui-city-table",
            "publisher": "Example Agency",
            "source_type": "government_record",
            "scope_population": "city residents",
        },
    ).json()
    citation = client.post("/citations", headers=headers, json={"source_id": source["id"], "locator": "table 1"}).json()
    linked = client.post(
        f"/claims/{claim['id']}/evidence",
        headers=headers,
        json={
            "citation_id": citation["id"],
            "stance": "supports",
            "claim_supported": "The city table records the city rate.",
        },
    )
    assert linked.status_code == 201, linked.text
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()
    assert summary["items"][0]["source_title"] == "City table"
    assert summary["items"][0]["scope_population"] == "city residents"
    assert summary["confidence"]["confidence_score"] is None or isinstance(summary["confidence"]["confidence_score"], float)
    assert any(flag["kind"] == "scope_mismatch" and flag["claim_evidence_id"] == linked.json()["id"] for flag in summary["scope_flags"])
    entry = client.post(
        "/library/entries",
        headers=headers,
        json={
            "question": "Did the city rate change?",
            "question_population": "city residents",
            "direct_answer": "yes",
            "status": "supported",
            "facts": "The city table records a change.",
            "interpretation": "The change answers the city question.",
            "uncertainty": "It does not answer a national question.",
            "supporting_claim_ids": [claim["id"]],
            "covered_points": ["The city table records a change."],
            "change_log": "Initial entry for the workspace page.",
        },
    )
    assert entry.status_code == 201, entry.text
    stored = client.get(f"/library/entries/{entry.json()['id']}").json()
    assert stored["sources"][0]["title"] == "City table"
    assert stored["supporting_claims"][0]["body"].startswith("The national rate")
    assert stored["current_version"]["direct_answer"] == "yes"
    assert isinstance(stored["current_version"]["confidence"], list)
    assert "confidence_score" in stored["current_version"]["confidence"][0]
