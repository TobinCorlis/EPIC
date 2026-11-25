from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole
from app.models.fable import FableLoreItem
from app.services.referee import DeterministicLoreReferee, validate_llm_ruling

client = TestClient(app)


def _moderator(email: str) -> dict:
    account = client.post("/auth/register", json={"email": email, "display_name": "Referee", "password": "verysecure123"})
    assert account.status_code == 201, account.text
    with SessionLocal() as db:
        user = db.get(User, account.json()["user"]["id"])
        user.role = UserRole.moderator
        db.commit()
    return {"Authorization": f"Bearer {account.json()['access_token']}"}


def test_deterministic_referee_rules_only_submitted_moves():
    headers = _moderator("referee@example.com")
    member = client.post("/auth/register", json={"email": "participant@example.com", "display_name": "Debater", "password": "verysecure123"})
    member_headers = {"Authorization": f"Bearer {member.json()['access_token']}"}
    created = client.post("/fable/matchups", json={
        "title": "DEMO referee check",
        "question": "DEMO fiction. Which recorded move stands?",
        "mode": "debate",
        "personal_knowledge_only": True,
        "participants": ["Lantern", "Comet"],
    })
    assert created.status_code == 201, created.text
    matchup_id = created.json()["id"]
    settings = client.patch(f"/fable/matchups/{matchup_id}/settings", headers=headers, json={
        "referee_mode": "ai_auto",
        "canon_only": True,
        "personal_knowledge_only": True,
    })
    assert settings.status_code == 200, settings.text
    lore = client.post(f"/fable/matchups/{matchup_id}/lore", json={
        "work_title": "Lantern Tales",
        "installment": "issue 1",
        "pinpoint": "page 4",
        "canon_status": "primary_canon",
        "body": "Lantern throws one glass marble.",
    }).json()
    lantern = next(person for person in created.json()["participants"] if person["name"] == "Lantern")
    moves = [
        ("Lantern throws one glass marble.", "allowed"),
        ("Lantern throws a marble that destroys a planet.", "disallowed"),
        ("Comet reads minds.", "unverified"),
    ]
    for text, _expected in moves:
        posted = client.post(f"/fable/matchups/{matchup_id}/moves", json={
            "participant_id": lantern["id"],
            "move_text": text,
            "claimed_source": "Lantern Tales, issue 1, page 4",
            "lore_item_id": lore["id"],
        })
        assert posted.status_code == 201, posted.text
    stored = client.get(f"/fable/matchups/{matchup_id}").json()
    by_text = {move["move_text"]: move for move in stored["moves"]}
    assert by_text["Lantern throws one glass marble."]["ruling"] == "allowed"
    assert by_text["Lantern throws a marble that destroys a planet."]["ruling"] == "disallowed"
    assert "magnitude" in by_text["Lantern throws a marble that destroys a planet."]["reason"]
    assert by_text["Comet reads minds."]["ruling"] == "unverified"
    assert all(move["ruled_by"] == "ai" for move in stored["moves"])
    assert stored["ai_outcome"] is None
    blocked = client.post(f"/fable/matchups/{matchup_id}/automated-referee", headers=member_headers)
    assert blocked.status_code == 403
    queue = client.get("/fable/referee/queue", headers=headers)
    assert queue.status_code == 200


def test_override_keeps_the_ai_ruling_and_llm_cannot_invent_lore():
    headers = _moderator("override@example.com")
    created = client.post("/fable/matchups", json={
        "title": "Override demo",
        "question": "DEMO fiction.",
        "mode": "debate",
        "participants": ["Lantern", "Comet"],
    }).json()
    client.patch(f"/fable/matchups/{created['id']}/settings", headers=headers, json={
        "referee_mode": "ai_suggest",
        "canon_only": True,
        "personal_knowledge_only": True,
    })
    lore = client.post(f"/fable/matchups/{created['id']}/lore", json={
        "work_title": "Lantern Tales",
        "installment": "issue 1",
        "pinpoint": "page 4",
        "canon_status": "primary_canon",
        "body": "Lantern throws one glass marble.",
    }).json()
    move = client.post(f"/fable/matchups/{created['id']}/moves", json={
        "participant_id": created["participants"][0]["id"],
        "move_text": "Lantern throws one glass marble.",
        "claimed_source": "Lantern Tales, issue 1, page 4",
    }).json()
    assert move["ruling"] is None
    queue = client.get("/fable/referee/queue", headers=headers).json()
    proposal = next(row for row in queue if row["move_id"] == move["id"])
    assert proposal["ruled_by"] == "ai"
    assert proposal["provider_name"] == "deterministic-lore"
    overridden = client.post(f"/fable/rulings/{proposal['id']}/override", headers=headers, json={
        "ruling": "unverified",
        "reason": "The moderator records a narrower reading of the same move.",
        "citation": "Lantern Tales, issue 1, page 4",
        "override_reason": "The cited panel is ambiguous about who throws it.",
    })
    assert overridden.status_code == 200, overridden.text
    history = overridden.json()["history"]
    assert [row["status"] for row in history] == ["proposed", "overridden"]
    assert history[0]["ruled_by"] == "ai"
    assert history[1]["ruled_by"] == "moderator"
    with SessionLocal() as db:
        item = db.get(FableLoreItem, lore["id"])
        fallback = validate_llm_ruling(
            {"ruling": "allowed", "reason": "Invented.", "lore_item_ids": [item.id + 50], "confidence": 0.99},
            [item],
        )
    assert fallback.ruling == "unverified"
    assert fallback.lore_item_ids == []
    direct = DeterministicLoreReferee().rule(
        "Lantern throws one glass marble.",
        "Missing Comic, issue 9, page 1",
        [item],
        canon_only=True,
    )
    assert direct.ruling == "disallowed"
    assert direct.lore_item_ids == []


def test_matchup_detail_includes_ruling_history_and_seed_is_idempotent():
    headers = _moderator("detail@example.com")
    created = client.post("/fable/matchups", json={
        "title": "Detail history",
        "question": "DEMO fiction.",
        "mode": "debate",
        "participants": ["Lantern", "Comet"],
    }).json()
    client.patch(f"/fable/matchups/{created['id']}/settings", headers=headers, json={
        "referee_mode": "ai_auto", "canon_only": True, "personal_knowledge_only": True,
    })
    client.post(f"/fable/matchups/{created['id']}/lore", json={
        "work_title": "Lantern Tales", "installment": "issue 1", "pinpoint": "page 4",
        "canon_status": "primary_canon", "body": "Lantern throws one glass marble.",
    })
    client.post(f"/fable/matchups/{created['id']}/moves", json={
        "participant_id": created["participants"][0]["id"],
        "move_text": "Lantern throws one glass marble.",
        "claimed_source": "Lantern Tales, issue 1, page 4",
    })
    detail = client.get(f"/fable/matchups/{created['id']}").json()
    history = detail["moves"][0]["rulings"]
    assert history
    assert history[0]["reason"]
    assert "Lantern Tales" in history[0]["citation"]
    assert "issue 1" in history[0]["citation"]
    assert "page 4" in history[0]["citation"]
    assert history[0]["lore_item_ids"]
    assert history[0]["ruled_by"] == "ai"
    assert history[0]["provider_name"] == "deterministic-lore"
    assert history[0]["confidence"] is not None
    assert detail["referee_mode"] == "ai_auto"
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "scripts" / "seed_fable_demo.py"
    spec = importlib.util.spec_from_file_location("seed_fable_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first = module.seed()
    second = module.seed()
    assert first == second
    from app.models.fable import FableMatchup, FableRuling, FableMove
    with SessionLocal() as db:
        titles = [row[0] for row in db.query(FableMatchup.title).filter(FableMatchup.title.like("DEMO:%")).all()]
        assert titles.count("DEMO: Lantern vs Comet") == 1
        assert titles.count("DEMO: Lantern vs Comet (suggest)") == 1
        suggest = db.query(FableMatchup).filter(FableMatchup.title == "DEMO: Lantern vs Comet (suggest)").one()
        proposed = (
            db.query(FableRuling)
            .join(FableMove, FableMove.id == FableRuling.move_id)
            .filter(FableMove.matchup_id == suggest.id, FableRuling.status == "proposed")
            .count()
        )
        assert proposed >= 1
    page = Path(__file__).resolve().parents[1].joinpath("app/static/app.js").read_text()
    assert "Run AI referee on submitted moves" in page
    assert "Automated AI refereeing is not implemented" not in page
    assert "Save room settings" in page


def test_evidence_checks_use_only_recorded_links():
    headers = _moderator("checks@example.com")
    debate = client.post("/debates", json={"title": "Check debate", "fixed_question": "Is the cited record findable?"}).json()
    claim = client.post(f"/debates/{debate['id']}/claims", json={"body": "The missing study measured it.", "claim_type": "factual"}).json()
    source = client.post("/sources", json={
        "title": "Missing study",
        "url": "https://example.edu/missing-study-check",
        "publisher": "Nowhere",
        "source_type": "peer_reviewed",
    }).json()
    marked = client.post(f"/sources/{source['id']}/record-review", headers=headers, json={"status": "no_record_found", "note": "The study could not be located."})
    assert marked.status_code == 200, marked.text
    citation = client.post("/citations", json={"source_id": source["id"], "locator": "p. 1"}).json()
    linked = client.post(f"/claims/{claim['id']}/evidence", json={"citation_id": citation["id"], "stance": "supports", "claim_supported": "The study measured it."})
    assert linked.status_code == 201, linked.text
    flags = client.get(f"/debates/{debate['id']}/evidence-checks").json()["flags"]
    assert any(flag["kind"] == "not_findable" for flag in flags)
    assert all("who is right" not in flag["detail"].lower() for flag in flags)
