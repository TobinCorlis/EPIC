import itertools

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User, UserRole
from app.models.knowledge import ResearchJob

client = TestClient(app)
_seq = itertools.count()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


def _account(role: UserRole | None = None):
    email = f"{_uniq('library')}@example.com"
    created = client.post(
        "/auth/register",
        json={"email": email, "display_name": "Library User", "password": "verysecure123"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    if role is not None:
        with SessionLocal() as db:
            user = db.get(User, body["user"]["id"])
            user.role = role
            db.commit()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _reviewed_source(headers, title: str, url: str, source_type: str, published: str):
    created = client.post(
        "/sources",
        headers=headers,
        json={
            "title": title,
            "url": url,
            "publisher": title,
            "source_type": source_type,
            "publication_date": published,
        },
    )
    assert created.status_code == 201, created.text
    source = created.json()
    reviewed = client.post(
        f"/sources/{source['id']}/source-type-review",
        headers=headers,
        json={"note": "The published type matches the document."},
    )
    assert reviewed.status_code == 200, reviewed.text
    return source


def _claim_with_source(headers, source_id: int, body: str):
    debate = client.post(
        "/debates",
        json={"title": _uniq("Record"), "fixed_question": "What does the recorded source say?"},
    )
    assert debate.status_code == 201, debate.text
    claim = client.post(
        f"/debates/{debate.json()['id']}/claims",
        json={"body": body, "claim_type": "factual"},
    )
    assert claim.status_code == 201, claim.text
    citation = client.post("/citations", json={"source_id": source_id, "locator": "table 1"})
    assert citation.status_code == 201, citation.text
    linked = client.post(
        f"/claims/{claim.json()['id']}/evidence",
        json={
            "citation_id": citation.json()["id"],
            "stance": "supports",
            "claim_supported": body,
        },
    )
    assert linked.status_code == 201, linked.text
    return debate.json(), claim.json()


def _entry(headers, claim_id: int, question: str, covered: list[str], **scope):
    created = client.post(
        "/library/entries",
        headers=headers,
        json={
            "question": question,
            "direct_answer": "yes",
            "status": "supported",
            "facts": "The recorded source states the measured figure.",
            "interpretation": "That figure answers the question as asked.",
            "uncertainty": "The figure does not cover a later period.",
            "supporting_claim_ids": [claim_id],
            "covered_points": covered,
            "change_log": "Initial entry from the recorded source.",
            **scope,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_reused_answer_does_no_new_work_and_scope_prevents_a_false_match():
    headers, _user_id = _account(UserRole.moderator)
    source = _reviewed_source(
        headers, "Agency table", f"https://example.gov/{_uniq('table')}", "government_record", "2001-01-01T00:00:00"
    )
    question = "Did the agency publish the annual figure?"
    _debate, claim = _claim_with_source(headers, source["id"], "The agency published the annual figure in table 1.")
    entry = _entry(headers, claim["id"], question, ["The agency published the annual figure in table 1."])
    before = _job_queries()
    reused = client.post("/debates", json={"title": "Reuse", "fixed_question": question})
    assert reused.status_code == 201, reused.text
    body = reused.json()
    assert body["library_served"] is True
    assert body["library_entry_id"] == entry["id"]
    assert body["library_stale"] is False
    assert "Last reviewed" in body["library_notice"]
    assert _job_queries() == before
    found = client.get("/library/search", params={"q": "annual figure"})
    assert found.status_code == 200
    assert any(item["id"] == entry["id"] and item["current_version"]["direct_answer"] == "yes" for item in found.json())
    other_scope = client.post(
        "/debates",
        json={
            "title": "Other scope",
            "fixed_question": question,
            "question_population": "children",
        },
    )
    assert other_scope.json()["library_served"] is False
    assert other_scope.json()["library_entry_id"] is None


def test_omitted_point_is_the_only_new_work_and_resolution_versions_the_entry():
    headers, _user_id = _account(UserRole.moderator)
    source = _reviewed_source(
        headers, "Agency table", f"https://example.gov/{_uniq('table')}", "government_record", "2001-01-01T00:00:00"
    )
    question = "Did the agency publish the quarterly figure?"
    covered = "The agency published the quarterly figure in table 1."
    _debate, claim = _claim_with_source(headers, source["id"], covered)
    entry = _entry(headers, claim["id"], question, [covered])
    opened = client.post("/debates", json={"title": "Quarterly", "fixed_question": question}).json()
    already = client.post(
        f"/debates/{opened['id']}/claims",
        json={"body": covered, "claim_type": "factual"},
    )
    assert already.status_code == 201, already.text
    assert already.json()["library_point_status"] == "covered"
    assert "already covered" in already.json()["library_notice"]
    omitted = "A later audit found a second figure that the entry never discussed."
    added = client.post(
        f"/debates/{opened['id']}/claims",
        json={"body": omitted, "claim_type": "factual"},
    )
    assert added.status_code == 201, added.text
    assert added.json()["library_point_status"] == "new point, not yet researched"
    queries = [query for query in _job_queries() if omitted in query or covered in query]
    assert queries == [f"new point, not yet researched: {omitted}"]
    resolved = client.post(
        f"/library/points/{added.json()['library_point_id']}/resolve",
        headers=headers,
        json={
            "direct_answer": "yes",
            "status": "supported",
            "facts": "The later audit records a second figure.",
            "interpretation": "The original answer still holds and now includes that figure.",
            "uncertainty": "The audit does not change the earlier table.",
            "supporting_claim_ids": [claim["id"]],
            "change_log": "Resolved the omitted audit point against the recorded source.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    stored = client.get(f"/library/entries/{entry['id']}").json()
    assert len(stored["versions"]) == 2
    assert stored["versions"][0]["version_number"] == 1
    assert stored["versions"][1]["outcome"] == "revised"
    assert "omitted audit point" in stored["versions"][1]["change_log"]
    matches = client.get("/library/search", params={"q": question}).json()
    assert [item["id"] for item in matches if item["question"] == question] == [entry["id"]]


def test_upheld_request_records_who_when_why_and_a_new_version():
    headers, user_id = _account(UserRole.moderator)
    source = _reviewed_source(
        headers, "Agency table", f"https://example.gov/{_uniq('table')}", "government_record", "2001-01-01T00:00:00"
    )
    question = "Did the agency publish the upheld figure?"
    _debate, claim = _claim_with_source(headers, source["id"], "The agency published the upheld figure.")
    entry = _entry(headers, claim["id"], question, ["The agency published the upheld figure."])
    requested = client.post(
        f"/library/entries/{entry['id']}/reevaluations",
        headers=headers,
        json={"reason": "A reader asked for the table to be checked again."},
    )
    assert requested.status_code == 201, requested.text
    assert requested.json()["requested_by_user_id"] == user_id
    assert requested.json()["reason"].startswith("A reader asked")
    assert requested.json()["requested_at"]
    pending = client.get(f"/library/entries/{entry['id']}").json()
    assert pending["reevaluation_pending"] is True
    assert pending["status_label"] == "re-evaluation pending"
    decided = client.post(
        f"/library/reevaluations/{requested.json()['id']}/decision",
        headers=headers,
        json={"outcome": "upheld", "note": "The original table remains the strongest record."},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "upheld"
    assert decided.json()["winning_source_id"] == source["id"]
    assert decided.json()["winning_reason"]
    stored = client.get(f"/library/entries/{entry['id']}").json()
    assert stored["reevaluation_pending"] is False
    assert stored["current_version"]["outcome"] == "upheld"
    assert stored["current_version"]["version_number"] == 2
    assert stored["versions"][0]["outcome"] == "initial"


def test_newer_weaker_source_does_not_override_a_stronger_one():
    headers, _user_id = _account(UserRole.moderator)
    government = _reviewed_source(
        headers, "Agency table", f"https://example.gov/{_uniq('table')}", "government_record", "2001-01-01T00:00:00"
    )
    blog = _reviewed_source(
        headers, "Newer blog", f"https://blog.example/{_uniq('post')}", "user_generated", "2024-06-01T00:00:00"
    )
    question = "Did the agency publish the compared figure?"
    _debate, claim = _claim_with_source(headers, government["id"], "The agency published the compared figure.")
    entry = _entry(headers, claim["id"], question, ["The agency published the compared figure."])
    requested = client.post(
        f"/library/entries/{entry['id']}/reevaluations",
        headers=headers,
        json={"reason": "A newer blog disagrees with the table.", "new_source_id": blog["id"]},
    )
    assert requested.status_code == 201, requested.text
    decided = client.post(
        f"/library/reevaluations/{requested.json()['id']}/decision",
        headers=headers,
        json={"outcome": "upheld", "note": "Checked the blog against the agency table."},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["winning_source_id"] == government["id"]
    reason = decided.json()["winning_reason"].lower()
    assert "newer" in reason
    assert "does not override" in reason
    assert str(blog["id"]) in decided.json()["winning_reason"]
    stored = client.get(f"/library/entries/{entry['id']}").json()
    assert stored["current_version"]["outcome"] == "upheld"
    assert stored["versions"][0]["facts"] == stored["current_version"]["facts"]


def test_upstream_retraction_overturns_and_cascades_to_two_entries():
    headers, _user_id = _account(UserRole.moderator)
    source = _reviewed_source(
        headers, "Retracted study", f"https://example.edu/{_uniq('study')}", "peer_reviewed", "2010-01-01T00:00:00"
    )
    notice = _reviewed_source(
        headers, "Retraction notice", f"https://example.edu/{_uniq('notice')}", "peer_reviewed", "2020-01-01T00:00:00"
    )
    first_debate, first_claim = _claim_with_source(headers, source["id"], "The study measured the first outcome.")
    second_debate, second_claim = _claim_with_source(headers, source["id"], "The study measured the second outcome.")
    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": _uniq("Dossier"), "question": "What did the study measure?"},
    )
    assert dossier.status_code == 201, dossier.text
    knowledge_ids = []
    for claim in (first_claim, second_claim):
        stored = client.post(
            f"/knowledge/dossiers/{dossier.json()['id']}/claims",
            json={"body": claim["body"] + " recorded", "originating_claim_id": claim["id"]},
        )
        assert stored.status_code == 201, stored.text
        verified = client.post(
            "/verification-events",
            headers=headers,
            json={
                "subject_type": "knowledge_claim",
                "subject_id": stored.json()["id"],
                "result_status": "verified",
                "method": "Read the study PDF",
                "archive_url": "https://example.edu/archive/study",
            },
        )
        assert verified.status_code == 201, verified.text
        knowledge_ids.append(stored.json()["id"])
    from app.models.factcheck import SourceCheck

    with SessionLocal() as db:
        db.add(SourceCheck(
            source_id=source["id"],
            checker_name="crossref",
            checker_version="factcheck-v1",
            api_name="api.crossref.org",
            query="works/10.1000/example",
            response_id="10.1000/example",
            result="found",
            detail="Crossref has this DOI.",
        ))
        db.commit()
    source_event = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "source",
            "subject_id": source["id"],
            "result_status": "verified",
            "method": "Read the study PDF",
            "archive_url": "https://example.edu/archive/study",
        },
    )
    assert source_event.status_code == 201, source_event.text
    first_entry = _entry(headers, first_claim["id"], "Did the study measure the first outcome?", ["The study measured the first outcome."])
    second_entry = _entry(headers, second_claim["id"], "Did the study measure the second outcome?", ["The study measured the second outcome."])
    invalidation = client.post(
        "/library/invalidations",
        headers=headers,
        json={
            "subject_type": "source",
            "subject_id": source["id"],
            "kind": "retraction",
            "reason": "The journal retracted the study for fabricated data.",
            "source_id": notice["id"],
        },
    )
    assert invalidation.status_code == 201, invalidation.text
    assert invalidation.json()["source_id"] == notice["id"]
    for entry in (first_entry, second_entry):
        stored = client.get(f"/library/entries/{entry['id']}").json()
        assert stored["stale"] is True
        assert stored["reevaluation_pending"] is True
        assert stored["status_label"] == "re-evaluation pending"
        assert stored["current_version"] is None
        assert len(stored["requests"]) == 1
    for debate in (first_debate, second_debate):
        fetched = client.get(f"/debates/{debate['id']}").json()
        assert fetched["library_stale"] is True
    listed = client.get(f"/knowledge/dossiers/{dossier.json()['id']}/claims").json()
    by_id = {item["id"]: item for item in listed}
    for knowledge_id in knowledge_ids:
        item = by_id[knowledge_id]
        assert item["status"] == "unverified"
        assert any("invalidated:" in note["note"] and "not a legitimate past verification" in note["note"] for note in item["status_history"])
        assert any(correction["kind"] == "upstream_invalidation" for correction in item["corrections"])
    record = client.get(f"/sources/{source['id']}/record").json()
    assert record["retracted"] >= 1
    source_events = client.get(
        "/verification-events",
        params={"subject_type": "source", "subject_id": source["id"]},
    ).json()
    assert source_events[0]["mistake_reason"] == "The journal retracted the study for fabricated data."
    for entry in (first_entry, second_entry):
        request_id = client.get(f"/library/entries/{entry['id']}").json()["requests"][0]["id"]
        decided = client.post(
            f"/library/reevaluations/{request_id}/decision",
            headers=headers,
            json={"outcome": "overturned", "note": "The retraction removes the study as support."},
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["winning_source_id"] == notice["id"]
        assert "invalidated" in decided.json()["winning_reason"].lower()
        stored = client.get(f"/library/entries/{entry['id']}").json()
        assert [version["outcome"] for version in stored["versions"]] == ["initial", "overturned"]
        assert stored["current_version"] is None


def _job_queries() -> list[str]:
    with SessionLocal() as db:
        return [row[0] for row in db.query(ResearchJob.query).all()]
