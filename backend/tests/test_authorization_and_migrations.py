from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole

client = TestClient(app)


def register(email: str):
    response = client.post(
        "/auth/register",
        json={"email": email, "display_name": email.split("@")[0], "password": "verysecure123"},
    )
    assert response.status_code == 201
    return response.json()


def test_production_write_authorization_and_debate_ownership():
    previous = settings.enforce_authorization
    settings.enforce_authorization = True
    try:
        denied = client.post("/debates", json={"title": "Test", "fixed_question": "Is this protected?"})
        assert denied.status_code == 401

        owner = register("owner@example.com")
        other = register("other@example.com")
        created = client.post(
            "/debates",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            json={"title": "Protected debate", "fixed_question": "Should ownership govern writes?"},
        )
        assert created.status_code == 201
        debate = created.json()
        assert debate["owner_user_id"] == owner["user"]["id"]

        forbidden = client.post(
            f"/debates/{debate['id']}/claims",
            headers={"Authorization": f"Bearer {other['access_token']}"},
            json={"body": "A claim by a non-owner.", "claim_type": "factual"},
        )
        assert forbidden.status_code == 403
    finally:
        settings.enforce_authorization = previous


def test_administrator_role_can_be_persisted():
    account = register("admin-candidate@example.com")
    with SessionLocal() as db:
        user = db.get(User, account["user"]["id"])
        user.role = UserRole.administrator
        db.commit()
        db.refresh(user)
        assert user.role == UserRole.administrator


def test_alembic_configuration_is_present():
    root = Path(__file__).parents[1]
    assert (root / "alembic.ini").exists()
    assert (root / "alembic" / "env.py").exists()
    assert (root / "alembic" / "versions" / "0001_initial_schema.py").exists()
