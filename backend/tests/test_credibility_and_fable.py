import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole
from app.models.library import ReferenceEntryVersion

client = TestClient(app)
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _moderator(email: str) -> dict:
    account = client.post("/auth/register", json={"email": email, "display_name": "Reviewer", "password": "verysecure123"})
    assert account.status_code == 201, account.text
    with SessionLocal() as db:
        user = db.get(User, account.json()["user"]["id"])
        user.role = UserRole.moderator
        db.commit()
    return {"Authorization": f"Bearer {account.json()['access_token']}"}


def _source(headers, title, url, publisher, source_type="government_record"):
    created = client.post("/sources", headers=headers, json={"title": title, "url": url, "publisher": publisher, "source_type": source_type})
    assert created.status_code == 201, created.text
    reviewed = client.post(f"/sources/{created.json()['id']}/source-type-review", headers=headers, json={"note": "The published type matches the document."})
    assert reviewed.status_code == 200, reviewed.text
    return created.json()


def _claim(body: str):
    debate = client.post("/debates", json={"title": body[:40], "fixed_question": "What does this claim's own evidence show?"}).json()
    claim = client.post(f"/debates/{debate['id']}/claims", json={"body": body, "claim_type": "factual"})
    assert claim.status_code == 201, claim.text
    return claim.json()


def _link(claim_id, source_id, stance="supports"):
    citation = client.post("/citations", json={"source_id": source_id, "locator": "p. 1"}).json()
    linked = client.post(f"/claims/{claim_id}/evidence", json={"citation_id": citation["id"], "stance": stance, "claim_supported": "The recorded measurement."})
    assert linked.status_code == 201, linked.text


def _confidence(claim_id):
    summary = client.get(f"/claims/{claim_id}/evidence-summary")
    assert summary.status_code == 200, summary.text
    return summary.json()["confidence"]


def test_identity_does_not_change_a_claims_own_support():
    headers = _moderator("identity@example.com")
    rejected = client.post("/sources", json={"title": "Named group", "url": "https://example.org/group-weight", "publisher": "Flat Earth Society", "source_type": "government_record", "group_reputation": -1})
    assert rejected.status_code == 422
    disfavored = _source(headers, "Group table", "https://example.org/flat-table", "Flat Earth Society")
    academy = _source(headers, "Academy table", "https://example.org/academy-table", "National Academy")
    kept = _claim("The group table records a measured length.")
    other_source_claim = _claim("The academy table records a measured length.")
    _link(kept["id"], disfavored["id"])
    _link(other_source_claim["id"], academy["id"])
    kept_score = _confidence(kept["id"])
    academy_score = _confidence(other_source_claim["id"])
    assert kept_score["label"] == "Rated"
    assert kept_score["confidence_score"] == academy_score["confidence_score"]
    assert kept_score["confidence_score"] > 0
    unsupported = _claim("The same group also says the earth is flat.")
    bare = _confidence(unsupported["id"])
    assert bare["label"] == "Unsupported"
    assert bare["label"] != "Refuted"
    assert bare["contradicting_sources"] == []
    refuted = _claim("The same group concludes the horizon is fake.")
    _link(refuted["id"], disfavored["id"])
    geodetic = _source(headers, "Geodetic survey", "https://example.gov/geodetic-horizon", "National Geodetic Survey", "primary_law")
    _link(refuted["id"], geodetic["id"], "contradicts")
    assert _confidence(refuted["id"])["label"] == "Refuted"
    still = _confidence(kept["id"])
    assert still["label"] == "Rated"
    assert still["confidence_score"] == kept_score["confidence_score"]


def test_not_factually_answerable_is_not_scored_or_reused():
    headers = _moderator("fiction-question@example.com")
    source = _source(headers, "Release record", "https://example.gov/star-wars-release", "Studio archive")
    factual = _claim("The 1977 film was released in 1977.")
    _link(factual["id"], source["id"])
    debate = client.post("/debates", json={
        "title": "Crew matchup",
        "fixed_question": "Who would win, Star Wars or Star Trek?",
        "answerability": "not_factually_answerable",
        "answerability_reason": "The question is a fictional hypothetical.",
    })
    assert debate.status_code == 201, debate.text
    assert debate.json()["library_served"] is False
    assert debate.json()["library_entry_id"] is None
    blocked = client.post("/library/entries", headers=headers, json={
        "question": "Who would win, Star Wars or Star Trek?",
        "direct_answer": "gap",
        "status": "unresolved",
        "facts": "No factual winner is recorded.",
        "interpretation": "The question is hypothetical.",
        "uncertainty": "Canon is not a measurement.",
        "supporting_claim_ids": [factual["id"]],
        "covered_points": ["No factual winner is recorded."],
        "change_log": "Rejected fictional question.",
    })
    assert blocked.status_code == 422
    sub = client.post(f"/debates/{debate.json()['id']}/claims", json={"body": "The 1977 film was released in 1977.", "claim_type": "factual"})
    assert sub.status_code == 201, sub.text
    _link(sub.json()["id"], source["id"])
    scored = _confidence(sub.json()["id"])
    assert scored["label"] == "Rated"
    opinion = client.post(f"/debates/{debate.json()['id']}/claims", json={
        "body": "Star Wars would beat Star Trek.",
        "claim_type": "opinion",
        "answerability": "not_factually_answerable",
        "answerability_reason": "This is a fictional hypothetical, not a factual claim.",
    })
    assert opinion.status_code == 201, opinion.text
    plain = _confidence(opinion.json()["id"])
    assert plain["not_factually_answerable"] is True
    assert plain["confidence_score"] is None
    assert plain["label"] is None
    page = (STATIC / "app.js").read_text()
    assert "This question has no factual answer." in page
    kept = client.post("/library/entries", headers=headers, json={
        "question": "Was the 1977 film released in 1977?",
        "direct_answer": "yes",
        "status": "supported",
        "facts": "The release record states 1977.",
        "interpretation": "That is a factual sub-part, not the matchup.",
        "uncertainty": "It does not decide a fictional fight.",
        "supporting_claim_ids": [factual["id"]],
        "covered_points": ["The 1977 film was released in 1977."],
        "change_log": "Factual sub-part only.",
    })
    assert kept.status_code == 201, kept.text


def test_old_library_version_without_a_label_is_recomputed():
    headers = _moderator("relabel@example.com")
    source = _source(headers, "Relabel table", "https://example.gov/relabel-table", "Records office")
    claim = _claim("The relabel table records one row.")
    _link(claim["id"], source["id"])
    entry = client.post("/library/entries", headers=headers, json={
        "question": "Does the relabel table record one row?",
        "direct_answer": "yes",
        "status": "supported",
        "facts": "The table records one row.",
        "interpretation": "That answers the question.",
        "uncertainty": "It does not answer a later year.",
        "supporting_claim_ids": [claim["id"]],
        "covered_points": ["The table records one row."],
        "change_log": "Initial labeled entry.",
    })
    assert entry.status_code == 201, entry.text
    version_id = entry.json()["current_version"]["id"]
    with SessionLocal() as db:
        version = db.get(ReferenceEntryVersion, version_id)
        stored = json.loads(version.confidence_json)
        for item in stored:
            item.pop("label", None)
        version.confidence_json = json.dumps(stored)
        db.commit()
    refreshed = client.get(f"/library/entries/{entry.json()['id']}").json()
    assert refreshed["current_version"]["confidence"][0]["label"] in {"Rated", "Unsupported", "Refuted", "Unknown – not yet rated"}
    assert refreshed["current_version"]["confidence"][0]["label"] != "Rated" or "label" in json.dumps(refreshed["current_version"]["confidence"][0])


def test_fable_is_walled_off_and_debate_outcomes_stay_separate():
    headers = _moderator("fable@example.com")
    ai = client.post("/fable/matchups", json={
        "title": "Batman versus Spider-Man AI",
        "question": "Who would win, Batman or Spider-Man?",
        "mode": "ai_matchup",
        "participants": ["Batman", "Spider-Man"],
    })
    assert ai.status_code == 201, ai.text
    run = client.post(f"/fable/matchups/{ai.json()['id']}/automated-run")
    assert run.status_code == 200, run.text
    assert run.json()["automated_analysis"] == "not_implemented"
    assert run.json()["ai_outcome"] is None
    debate = client.post("/fable/matchups", json={
        "title": "Batman versus Spider-Man debate",
        "question": "Who would win, Batman or Spider-Man?",
        "mode": "debate",
        "personal_knowledge_only": True,
        "participants": ["Batman debater", "Spider-Man debater"],
    })
    assert debate.status_code == 201, debate.text
    assert debate.json()["personal_knowledge_only"] is True
    assert debate.json()["fiction"] is True
    matchup_id = debate.json()["id"]
    lore = client.post(f"/fable/matchups/{matchup_id}/lore", json={
        "work_title": "Amazing Fantasy",
        "installment": "issue 15",
        "pinpoint": "page 8",
        "canon_status": "primary_canon",
        "body": "Spider-Man dodges a blow.",
    })
    assert lore.status_code == 201, lore.text
    step = client.post(f"/fable/matchups/{matchup_id}/steps", json={"step_number": 1, "body": "The cited panel shows a dodge.", "lore_item_ids": [lore.json()["id"]]})
    assert step.status_code == 201, step.text
    note = client.post(f"/fable/matchups/{matchup_id}/canon-notes", json={"kind": "silent", "note": "Canon does not stage this fight."})
    assert note.status_code == 201, note.text
    batman = next(person for person in debate.json()["participants"] if person["name"] == "Batman debater")
    move = client.post(f"/fable/matchups/{matchup_id}/moves", json={
        "participant_id": batman["id"],
        "move_text": "Batman throws a batarang.",
        "claimed_source": "Detective Comics 27, page 3",
    })
    assert move.status_code == 201, move.text
    extra = client.post(f"/fable/moves/{move.json()['id']}/ruling", headers=headers, json={
        "ruling": "allowed",
        "reason": "The cited page shows the throw.",
        "citation": "Detective Comics 27, page 3",
        "counter": "Spider-Man dodges with spider-sense.",
    })
    assert extra.status_code == 422
    ruling = client.post(f"/fable/moves/{move.json()['id']}/ruling", headers=headers, json={
        "ruling": "allowed",
        "reason": "The cited page shows the throw. No counter was added.",
        "citation": "Detective Comics 27, page 3",
    })
    assert ruling.status_code == 200, ruling.text
    assert ruling.json()["ruled_by"] == "moderator"
    missing = client.post(f"/fable/matchups/{matchup_id}/debate-outcome", headers=headers, json={
        "outcome": "Batman",
        "note": "Spider-Man raised no counter, so the debate uses only the batarang.",
        "move_ids": [move.json()["id"], 999999],
    })
    assert missing.status_code == 422
    decided = client.post(f"/fable/matchups/{matchup_id}/debate-outcome", headers=headers, json={
        "outcome": "Batman",
        "note": "Only the batarang was raised and allowed. The unused dodge was not introduced.",
        "move_ids": [move.json()["id"]],
    })
    assert decided.status_code == 200, decided.text
    assert decided.json()["debate_outcome"] == "Batman"
    assert decided.json()["debate_outcome_label"] == "debate"
    assert decided.json()["ai_outcome"] is None
    assert decided.json()["ai_outcome_label"] == "ai_matchup"
    assert len(decided.json()["moves"]) == 1
    referee = client.post(f"/fable/matchups/{matchup_id}/automated-referee", headers=headers)
    assert referee.status_code == 200, referee.text
    assert referee.json()["moves_added"] == 0
    assert "did not introduce a counter" in referee.json()["detail"].lower()
    again = client.get(f"/fable/matchups/{matchup_id}").json()
    assert len(again["moves"]) == 1
    assert again["moves"][0]["ruling"] == "allowed"
    ai_again = client.get(f"/fable/matchups/{ai.json()['id']}").json()
    assert ai_again["ai_outcome"] is None
    assert ai_again["debate_outcome"] is None
    help_route = client.post(f"/fable/matchups/{matchup_id}/help", json={"question": "What power should I use?"})
    assert help_route.status_code == 404
    paths = client.get("/openapi.json").json()["paths"]
    fable_paths = [path for path in paths if path.startswith("/fable")]
    assert not any(any(word in path for word in ("help", "coach", "suggest", "ask")) for path in fable_paths)
    script = (STATIC / "app.js").read_text().lower()
    assert "askai" not in script
    assert "/fable/help" not in script
    assert "suggest a power" not in script
    assert "no control to ask the ai for help" in script
    assert "epic fable" in (STATIC / "index.html").read_text().lower()
    found = client.get("/library/search", params={"q": "Batman versus Spider-Man"})
    assert found.status_code == 200
    assert found.json() == []
