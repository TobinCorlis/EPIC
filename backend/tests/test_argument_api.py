from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make_debate(title="Structured Debate"):
    response = client.post(
        "/debates",
        json={"title": title, "fixed_question": "Does the evidence establish the proposition?"},
    )
    assert response.status_code == 201
    return response.json()


def make_participant(debate_id, name, role="debater", side="affirmative"):
    response = client.post(
        f"/debates/{debate_id}/participants",
        json={"display_name": name, "role": role, "side": side},
    )
    assert response.status_code == 201
    return response.json()


def test_structured_argument_and_ruling_workflow():
    debate = make_debate()
    debater = make_participant(debate["id"], "Affirmative Debater")
    moderator = make_participant(debate["id"], "EPIC Moderator", "moderator", "neutral")

    claim = client.post(
        f"/debates/{debate['id']}/claims",
        json={"body": "The official record contains the relevant finding.", "claim_type": "factual"},
    )
    assert claim.status_code == 201

    premise = client.post(
        f"/debates/{debate['id']}/arguments",
        json={
            "participant_id": debater["id"],
            "claim_id": claim.json()["id"],
            "node_type": "premise",
            "body": "The official record is direct evidence of the finding.",
        },
    )
    assert premise.status_code == 201
    assert premise.json()["side"] == "affirmative"
    assert premise.json()["verification_status"] == "unverified"

    conclusion = client.post(
        f"/debates/{debate['id']}/arguments",
        json={
            "participant_id": debater["id"],
            "parent_node_id": premise.json()["id"],
            "node_type": "conclusion",
            "body": "Therefore, the proposition is supported.",
        },
    )
    assert conclusion.status_code == 201

    ruling = client.post(
        f"/debates/{debate['id']}/rulings",
        json={
            "moderator_id": moderator["id"],
            "argument_node_id": premise.json()["id"],
            "outcome": "allowed",
            "rationale": "The premise is on topic and linked to a factual claim.",
            "rule_reference": "EPIC-ARG-1",
        },
    )
    assert ruling.status_code == 201

    updated = client.get(f"/debates/{debate['id']}/arguments")
    assert updated.status_code == 200
    assert updated.json()[0]["verification_status"] == "unverified"

    audit = client.get(f"/debates/{debate['id']}/rulings")
    assert audit.status_code == 200
    assert audit.json()[0]["rationale"].startswith("The premise")


def test_evidence_challenge_can_be_resolved_by_moderator():
    debate = make_debate("Evidence Challenge")
    debater = make_participant(debate["id"], "Challenger", "debater", "negative")
    moderator = make_participant(debate["id"], "Human Moderator", "moderator", "neutral")

    claim = client.post(
        f"/debates/{debate['id']}/claims",
        json={"body": "The report states a measurable result.", "claim_type": "factual"},
    ).json()
    source = client.post(
        "/sources",
        json={
            "title": "Challengeable report",
            "url": "https://example.org/challenge-report",
            "publisher": "Example Institute",
            "source_type": "expert_analysis",
        },
    ).json()
    citation = client.post(
        "/citations",
        json={"source_id": source["id"], "locator": "p. 8", "excerpt": "A measurable result."},
    ).json()
    link = client.post(
        f"/claims/{claim['id']}/evidence",
        json={
            "citation_id": citation["id"],
            "stance": "supports",
            "relevance_score": 0.7,
            "claim_supported": "The report states a measurable result.",
        },
    ).json()

    challenge = client.post(
        f"/claim-evidence/{link['id']}/challenges",
        json={
            "challenger_id": debater["id"],
            "reason": "The excerpt omits a limitation stated on the next page.",
            "requested_remedy": "Mark the evidence as contextual rather than conclusive.",
        },
    )
    assert challenge.status_code == 201
    assert challenge.json()["status"] == "open"

    ruling = client.post(
        f"/debates/{debate['id']}/rulings",
        json={
            "moderator_id": moderator["id"],
            "challenge_id": challenge.json()["id"],
            "outcome": "challenge_upheld",
            "rationale": "The omitted limitation materially changes the weight of the excerpt.",
        },
    )
    assert ruling.status_code == 201

    resolved = client.patch(
        f"/challenges/{challenge.json()['id']}",
        json={"status": "upheld", "response": "Limitation confirmed during review."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None


def test_non_moderator_cannot_issue_ruling_and_cross_debate_links_are_blocked():
    debate_a = make_debate("Debate A")
    debate_b = make_debate("Debate B")
    participant_a = make_participant(debate_a["id"], "A Debater")
    participant_b = make_participant(debate_b["id"], "B Debater")

    forbidden = client.post(
        f"/debates/{debate_a['id']}/rulings",
        json={
            "moderator_id": participant_a["id"],
            "argument_node_id": 999,
            "outcome": "warning",
            "rationale": "This should not be authorized.",
        },
    )
    assert forbidden.status_code == 403

    cross_debate = client.post(
        f"/debates/{debate_a['id']}/arguments",
        json={
            "participant_id": participant_b["id"],
            "node_type": "premise",
            "body": "This participant belongs to another debate.",
        },
    )
    assert cross_debate.status_code == 409
