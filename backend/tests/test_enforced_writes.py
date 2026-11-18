import pytest
from fastapi.testclient import TestClient

from app.cli import AdminBootstrapError, create_first_admin
from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole
from app.models.knowledge import ResearchJob, ResearchJobStatus

client = TestClient(app)


def register(email: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"email": email, "display_name": email.split("@")[0], "password": "verysecure123"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_enforced_knowledge_argument_and_challenge_writes_require_permission():
    previous = settings.enforce_authorization
    settings.enforce_authorization = True
    try:
        denied_dossier = client.post(
            "/knowledge/dossiers",
            json={"title": "Locked dossier", "question": "Who may write?"},
        )
        assert denied_dossier.status_code == 401

        owner = register("writer-owner@example.com")
        other = register("writer-other@example.com")
        owner_headers = auth(owner["access_token"])
        other_headers = auth(other["access_token"])

        debate = client.post(
            "/debates",
            headers=owner_headers,
            json={"title": "Guarded debate", "fixed_question": "Are writes authenticated?"},
        )
        assert debate.status_code == 201, debate.text
        debate_id = debate.json()["id"]
        participant = client.post(
            f"/debates/{debate_id}/participants",
            headers=owner_headers,
            json={"display_name": "Owner debater", "role": "debater", "side": "affirmative"},
        ).json()

        anonymous_node = client.post(
            f"/debates/{debate_id}/arguments",
            json={"participant_id": participant["id"], "node_type": "premise", "body": "Unauthenticated premise."},
        )
        assert anonymous_node.status_code == 401
        foreign_node = client.post(
            f"/debates/{debate_id}/arguments",
            headers=other_headers,
            json={"participant_id": participant["id"], "node_type": "premise", "body": "Someone else's premise."},
        )
        assert foreign_node.status_code == 403
        owned_node = client.post(
            f"/debates/{debate_id}/arguments",
            headers=owner_headers,
            json={"participant_id": participant["id"], "node_type": "premise", "body": "Owner premise."},
        )
        assert owned_node.status_code == 201, owned_node.text

        claim = client.post(
            f"/debates/{debate_id}/claims",
            headers=owner_headers,
            json={"body": "The record contains the finding.", "claim_type": "factual"},
        ).json()
        source = client.post(
            "/sources",
            headers=owner_headers,
            json={"title": "Guarded record", "url": "https://example.gov/guarded-record", "source_type": "government_record"},
        ).json()
        citation = client.post(
            "/citations",
            headers=owner_headers,
            json={"source_id": source["id"], "locator": "p. 2"},
        ).json()
        link = client.post(
            f"/claims/{claim['id']}/evidence",
            headers=owner_headers,
            json={
                "citation_id": citation["id"],
                "stance": "supports",
                "claim_supported": "The record contains the finding.",
            },
        ).json()

        anonymous_challenge = client.post(
            f"/claim-evidence/{link['id']}/challenges",
            json={"challenger_id": participant["id"], "reason": "The page does not say that."},
        )
        assert anonymous_challenge.status_code == 401
        challenge = client.post(
            f"/claim-evidence/{link['id']}/challenges",
            headers=owner_headers,
            json={"challenger_id": participant["id"], "reason": "The page does not say that."},
        )
        assert challenge.status_code == 201, challenge.text
        anonymous_resolve = client.patch(
            f"/challenges/{challenge.json()['id']}",
            json={"status": "answered", "response": "Unchecked response."},
        )
        assert anonymous_resolve.status_code == 401
        resolved = client.patch(
            f"/challenges/{challenge.json()['id']}",
            headers=owner_headers,
            json={"status": "answered", "response": "Owner reviewed the page."},
        )
        assert resolved.status_code == 200, resolved.text

        dossier = client.post(
            "/knowledge/dossiers",
            headers=owner_headers,
            json={"title": "Guarded knowledge", "question": "Who may add a claim?"},
        )
        assert dossier.status_code == 201, dossier.text
        added = client.post(
            f"/knowledge/dossiers/{dossier.json()['id']}/claims",
            headers=owner_headers,
            json={"body": "The guarded claim is still unverified."},
        )
        assert added.status_code == 201
        job = client.post(
            "/knowledge/jobs",
            headers=owner_headers,
            json={"query": "Find the official record", "dossier_id": dossier.json()["id"]},
        )
        assert job.status_code == 201
        with SessionLocal() as db:
            row = db.get(ResearchJob, job.json()["id"])
            row.status = ResearchJobStatus.cancelled
            db.commit()

        member_review = client.patch(
            "/knowledge/contradictions/999999",
            headers=owner_headers,
            json={"status": "confirmed"},
        )
        assert member_review.status_code == 403
        with SessionLocal() as db:
            account = db.get(User, owner["user"]["id"])
            account.role = UserRole.moderator
            db.commit()
        missing_review = client.patch(
            "/knowledge/contradictions/999999",
            headers=owner_headers,
            json={"status": "confirmed"},
        )
        assert missing_review.status_code == 404
    finally:
        settings.enforce_authorization = previous


def test_create_first_admin_command_runs_once():
    with SessionLocal() as db:
        for user in db.query(User).filter(User.role == UserRole.administrator):
            user.role = UserRole.member
        db.commit()
    created = create_first_admin("first-admin@example.com", "First Admin", "verysecure123")
    assert created.role == UserRole.administrator
    with pytest.raises(AdminBootstrapError, match="already exists"):
        create_first_admin("another-admin@example.com", "Another Admin", "verysecure123")
