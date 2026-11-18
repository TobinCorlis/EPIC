from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _debate(question: str, **scope):
    payload = {"title": "Scope debate", "fixed_question": question, **scope}
    created = client.post("/debates", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def _claim(debate_id: int, body: str, **scope):
    created = client.post(f"/debates/{debate_id}/claims", json={"body": body, "claim_type": "factual", **scope})
    assert created.status_code == 201, created.text
    return created.json()


def _support(claim_id: int, url: str, stance: str = "supports", **scope):
    source = client.post(
        "/sources",
        json={"title": url, "url": url, "publisher": "Recorded publisher", "source_type": "unknown", **scope},
    )
    assert source.status_code == 201, source.text
    citation = client.post("/citations", json={"source_id": source.json()["id"], "excerpt": scope.get("scope_population", "")})
    assert citation.status_code == 201, citation.text
    linked = client.post(
        f"/claims/{claim_id}/evidence",
        json={
            "citation_id": citation.json()["id"],
            "stance": stance,
            "claim_supported": "The recorded measurement.",
        },
    )
    assert linked.status_code == 201, linked.text
    return linked.json()


def _summary(claim_id: int):
    summary = client.get(f"/claims/{claim_id}/evidence-summary")
    assert summary.status_code == 200, summary.text
    return summary.json()


def test_scope_mismatch_and_question_drift_need_review_and_stay_on_topic():
    debate = _debate(
        "Did the city rate rise in 2019?",
        question_population="city residents",
        question_timeframe="2019",
        question_geography="one city",
    )
    claim = _claim(
        debate["id"],
        "The national rate rose.",
        scope_population="national residents",
        scope_timeframe="2019",
        scope_geography="one city",
    )
    _support(claim["id"], "https://example.gov/city-2019", scope_population="city residents", scope_timeframe="2019")
    listed = client.get(f"/debates/{debate['id']}/claims").json()[0]
    assert listed["on_topic"] is True
    assert listed["needs_review"] is True
    flags = _summary(claim["id"])["scope_flags"]
    kinds = {(flag["kind"], flag["dimension"]) for flag in flags}
    assert ("scope_mismatch", "population") in kinds
    assert ("question_drift", "population") in kinds
    assert all("Needs review" in flag["note"] for flag in flags)
    assert "not a finding" in flags[0]["note"]


def test_overgeneralization_from_entered_wording():
    debate = _debate("Does the study support the stated claim?")
    claim = _claim(debate["id"], "The treatment causes recovery in all patients nationwide.")
    _support(
        claim["id"],
        "https://example.edu/some-patients",
        scope_population="some patients",
        scope_study_type="correlation",
        scope_geography="one city",
    )
    flags = _summary(claim["id"])["scope_flags"]
    dimensions = {flag["dimension"] for flag in flags if flag["kind"] == "overgeneralization"}
    assert {"breadth", "causation", "geography"} <= dimensions


def test_single_study_is_an_outlier_only_against_recorded_contrary_evidence():
    debate = _debate("Is the single study representative?")
    alone = _claim(debate["id"], "The single study is the result.")
    _support(alone["id"], "https://example.edu/alone")
    assert [flag for flag in _summary(alone["id"])["scope_flags"] if flag["kind"] == "outlier"] == []

    conflicted = _claim(debate["id"], "The single study is the result for everyone.")
    _support(conflicted["id"], "https://example.edu/one-study")
    _support(conflicted["id"], "https://example.edu/contrary", stance="contradicts")
    outliers = [flag for flag in _summary(conflicted["id"])["scope_flags"] if flag["kind"] == "outlier"]
    assert len(outliers) == 1
    assert outliers[0]["source_text"]
