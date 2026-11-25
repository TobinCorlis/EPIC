"""Automated source checks. Every HTTP call is mocked unless EPIC_LIVE_FACTCHECK=1."""
import itertools
import json
import os
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal, commit_with_retry
from app.main import app
from app.models.auth import User, UserRole
from app.models.factcheck import FactcheckCache, SourceCheck, VerificationJob
from app.models.library import UpstreamInvalidation
from app.services.factcheck.status import findability_for_source
from app.services.factcheck.checkers import validate_llm_assessment
from app.services.factcheck.http import HttpResponse, HttpxTransport, get_transport, set_transport, user_agent
from app.services.factcheck.runner import enqueue_verification, process_verification_job
from app.services.factcheck.text import extract_doi, extract_federal_register, quote_match

client = TestClient(app)
_seq = itertools.count()


@pytest.fixture(autouse=True)
def reset_transport():
    set_transport(None)
    yield
    set_transport(None)
    settings.factcheck_save_page_now = False
    settings.factcheck_llm_base_url = ""
    settings.factcheck_llm_api_key = ""
    settings.factcheck_llm_model = ""


class FakeTransport:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, headers=None, data=None):
        self.calls.append((method, url))
        for predicate, response in self.routes:
            if predicate(method, url):
                return response
        return HttpResponse(status=None, url=url, body=b"", content_type="", error="no route")


def json_response(status, payload, url="https://example.test/response"):
    return HttpResponse(status=status, url=url, body=json.dumps(payload).encode(), content_type="application/json")


def text_response(status, body, url, content_type="text/html"):
    return HttpResponse(status=status, url=url, body=body.encode(), content_type=content_type)


def _user(role=None):
    email = f"factcheck-{next(_seq)}@example.com"
    created = client.post(
        "/auth/register",
        json={"email": email, "display_name": "Fact Checker", "password": "verysecure123"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    if role is not None:
        with SessionLocal() as db:
            user = db.get(User, body["user"]["id"])
            user.role = role
            db.commit()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _source(headers, title, url, document=None, source_type="peer_reviewed", author="Ada Lovelace", year="2020-01-01T00:00:00"):
    payload = {
        "title": title,
        "document_reference": document,
        "publisher": "Journal of Examples",
        "author": author,
        "publication_date": year,
        "source_type": source_type,
    }
    if url is not None:
        payload["url"] = url
    created = client.post(
        "/sources",
        headers=headers,
        json=payload,
    )
    assert created.status_code == 201, created.text
    return created.json()


def _debate_claim(body, role="substantive"):
    debate = client.post(
        "/debates",
        json={"title": f"Fact {next(_seq)}", "fixed_question": "Did the cited record say this?", "description": "A fact check."},
    ).json()
    claim = client.post(
        f"/debates/{debate['id']}/claims",
        json={"body": body, "claim_type": "factual", "claim_role": role},
    )
    assert claim.status_code == 201, claim.text
    return claim.json()


def _link(claim_id, source_id, excerpt=None, stance="supports"):
    citation = client.post(
        "/citations",
        json={"source_id": source_id, "locator": "p. 4", "excerpt": excerpt},
    ).json()
    linked = client.post(
        f"/claims/{claim_id}/evidence",
        json={"citation_id": citation["id"], "stance": stance, "claim_supported": "The cited passage."},
    )
    assert linked.status_code == 201, linked.text
    return citation


def _review(headers, source_id):
    reviewed = client.post(
        f"/sources/{source_id}/source-type-review",
        headers=headers,
        json={"note": "The published type matches the document."},
    )
    assert reviewed.status_code == 200, reviewed.text


def _crossref(doi, title, author="Lovelace", year=2020, journal="Journal of Examples", notices=None):
    message = {
        "DOI": doi,
        "title": [title],
        "author": [{"family": author, "given": "Ada"}],
        "issued": {"date-parts": [[year]]},
        "container-title": [journal],
        "update-to": notices or [],
    }
    return json_response(200, {"status": "ok", "message": message}, f"https://api.crossref.org/works/{doi}")


def test_identifiers_and_exact_quote():
    assert extract_doi("see https://doi.org/10.1000/abc.1).") == "10.1000/abc.1"
    assert extract_federal_register("https://www.federalregister.gov/documents/2024/1/2/2024-12345") == "2024-12345"
    assert extract_federal_register("a paper from 2020-12345") is None
    result, score, snippet = quote_match("the shoreline did not rise", "<p>The shoreline did not rise after the measurement.</p>")
    assert result == "quote_found"
    assert score == 1.0
    assert "shoreline" in snippet


def test_crossref_match_is_recorded_and_is_not_verified():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "Measured shoreline", "https://doi.org/10.1000/shore")
    transport = FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/shore", "Measured shoreline")),
    ])
    set_transport(transport)
    checks = client.post(f"/sources/{source['id']}/checks", headers=headers)
    assert checks.status_code == 200, checks.text
    rows = checks.json()
    found = next(row for row in rows if row["checker_name"] == "crossref")
    assert found["result"] == "found"
    assert found["response_id"] == "10.1000/shore"
    assert found["evidence_url"] == "https://doi.org/10.1000/shore"
    assert "api.crossref.org" in found["api_name"]
    metadata = next(row for row in rows if row["checker_name"] == "metadata")
    assert metadata["result"] == "found"
    stored = client.get(f"/sources/{source['id']}").json()
    assert stored["verification_status"] == "unverified"
    again = client.post(f"/sources/{source['id']}/checks", headers=headers)
    assert len(again.json()) > len(rows)
    assert any(row["id"] == found["id"] for row in again.json())


def test_metadata_mismatch_is_review_not_absence():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "Measured shoreline", "https://doi.org/10.1000/mismatch")
    claim = _debate_claim("The paper measured the shoreline.")
    _link(claim["id"], source["id"])
    _review(headers, source["id"])
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/mismatch", "A different title entirely")),
    ]))
    checks = client.post(f"/sources/{source['id']}/checks", headers=headers).json()
    assert next(row["result"] for row in checks if row["checker_name"] == "crossref") == "found"
    assert next(row["result"] for row in checks if row["checker_name"] == "metadata") == "mismatch"
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()
    assert summary["confidence"]["label"] == "Weakly supported"
    flagged = client.get(f"/debates/{claim['debate_id']}/claims").json()[0]
    assert flagged["needs_review"] is True


def test_missing_doi_is_not_findable_even_when_the_tier_was_reviewed():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "Missing paper", "https://doi.org/10.1000/missing")
    claim = _debate_claim("The missing paper settles the question.")
    _link(claim["id"], source["id"])
    _review(headers, source["id"])
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, json_response(404, {"status": "404"})),
    ]))
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()
    confidence = summary["confidence"]
    assert confidence["label"] == "Unsupported"
    assert confidence["confidence_score"] == 0
    assert confidence["cited_source_note"] == "cited source: no record found"
    assert confidence["automated_source_check"] == "not_findable"
    assert "factcheck-v1" in confidence["factors"][0]["detail"]
    stored = client.get(f"/sources/{source['id']}").json()
    assert stored["verification_status"] == "unverified"


def test_network_failure_is_check_failed_and_not_verified():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "Unreachable paper", "https://doi.org/10.1000/down")
    claim = _debate_claim("The unreachable paper is still only unchecked.")
    _link(claim["id"], source["id"])
    _review(headers, source["id"])
    set_transport(FakeTransport([]))
    checks = client.post(f"/sources/{source['id']}/checks", headers=headers).json()
    assert any(row["result"] == "check_failed" and row["checker_name"] == "crossref" for row in checks)
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()
    assert summary["confidence"]["automated_source_check"] == "check_failed"
    assert summary["confidence"]["label"] == "Weakly supported"
    stored = client.get(f"/sources/{source['id']}").json()
    assert stored["verification_status"] == "unverified"
    blocked = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "source",
            "subject_id": source["id"],
            "result_status": "verified",
            "method": "Tried the DOI",
            "archive_url": "https://example.edu/archive/down",
        },
    )
    assert blocked.status_code == 409


def test_openalex_low_confidence_is_not_confirmed_and_a_strong_match_is():
    headers, _user_id = _user()
    weak = _source(headers, "Lantern marble study", None, document="report 1")
    set_transport(FakeTransport([
        (lambda method, url: "api.openalex.org" in url, json_response(200, {"results": [{
            "id": "https://openalex.org/W1",
            "display_name": "Completely unrelated mineral survey",
            "authorships": [{"author": {"display_name": "Other Person"}}],
        }]})),
    ]))
    weak_rows = client.post(f"/sources/{weak['id']}/checks", headers=headers).json()
    weak_hit = next(row for row in weak_rows if row["checker_name"] == "openalex")
    assert weak_hit["result"] == "low_confidence"
    assert weak_hit["match_score"] < 0.72
    strong = _source(headers, "Lantern marble study", None, document="report 2")
    set_transport(FakeTransport([
        (lambda method, url: "api.openalex.org" in url, json_response(200, {"results": [{
            "id": "https://openalex.org/W2",
            "display_name": "Lantern marble study",
            "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        }]})),
    ]))
    strong_rows = client.post(f"/sources/{strong['id']}/checks", headers=headers).json()
    assert next(row["result"] for row in strong_rows if row["checker_name"] == "openalex") == "found"


def test_retraction_cascades_and_blocks_verified():
    headers, user_id = _user(UserRole.moderator)
    source = _source(headers, "Retracted shoreline study", "https://doi.org/10.1000/retracted")
    claim = _debate_claim("The retracted study measured the shoreline.")
    _link(claim["id"], source["id"])
    _review(headers, source["id"])
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref(
            "10.1000/retracted",
            "Retracted shoreline study",
            notices=[{"type": "retraction", "DOI": "10.1000/notice", "label": "Retraction"}],
        )),
    ]))
    checks = client.post(f"/sources/{source['id']}/checks", headers=headers).json()
    assert any(row["result"] == "retracted" for row in checks)
    record = client.get(f"/sources/{source['id']}/record").json()
    assert record["retracted"] >= 1
    blocked = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "source",
            "subject_id": source["id"],
            "result_status": "verified",
            "method": "Read the PDF",
            "archive_url": "https://example.edu/archive/retracted",
        },
    )
    assert blocked.status_code == 409
    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": f"Retracted {next(_seq)}", "question": "Did the study measure the shoreline?"},
    ).json()
    knowledge = client.post(
        f"/knowledge/dossiers/{dossier['id']}/claims",
        json={"body": "The study measured the shoreline.", "originating_claim_id": claim["id"]},
    ).json()
    knowledge_blocked = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "knowledge_claim",
            "subject_id": knowledge["id"],
            "result_status": "verified",
            "method": "Read the PDF",
            "archive_url": "https://example.edu/archive/retracted",
        },
    )
    assert knowledge_blocked.status_code == 409
    assert user_id


def test_pubmed_retraction_publication_type():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "PubMed shoreline study", "https://pubmed.ncbi.nlm.nih.gov/1234567/", document="PMID: 1234567")
    set_transport(FakeTransport([
        (lambda method, url: "esummary" in url, json_response(200, {"result": {"1234567": {
            "uid": "1234567",
            "title": "PubMed shoreline study",
            "fulljournalname": "Journal of Examples",
            "sortpubdate": "2020/01/01",
            "authors": [{"name": "Ada Lovelace"}],
            "pubtype": ["Retracted Publication"],
        }}})),
    ]))
    rows = client.post(f"/sources/{source['id']}/checks", headers=headers).json()
    assert any(row["checker_name"] == "pubmed" and row["result"] == "found" for row in rows)
    assert any(row["result"] == "retracted" for row in rows)


def test_url_archive_is_recorded_only_when_a_snapshot_exists():
    headers, _user_id = _user()
    present = _source(headers, "Agency page", "https://example.gov/present", document="agency page", source_type="government_record")
    absent = _source(headers, "Agency missing page", "https://example.gov/absent", document="missing page", source_type="government_record")
    set_transport(FakeTransport([
        (lambda method, url: url.startswith("https://example.gov/present"), text_response(200, "<p>The table lists 12 hours.</p>", "https://example.gov/present")),
        (lambda method, url: "wayback/available" in url and "present" in url, json_response(200, {"archived_snapshots": {"closest": {
            "available": True,
            "url": "https://web.archive.org/web/20200101000000/https://example.gov/present",
            "timestamp": "20200101000000",
        }}})),
        (lambda method, url: url.startswith("https://example.gov/absent"), text_response(404, "missing", "https://example.gov/absent")),
        (lambda method, url: "wayback/available" in url and "absent" in url, json_response(200, {"archived_snapshots": {}})),
        (lambda method, url: "api.openalex.org" in url, json_response(200, {"results": []})),
    ]))
    client.post(f"/sources/{present['id']}/checks", headers=headers)
    stored = client.get(f"/sources/{present['id']}").json()
    assert stored["archive_url"].endswith("/present")
    assert stored["archived_at"]
    assert stored["verification_status"] == "unverified"
    client.post(f"/sources/{absent['id']}/checks", headers=headers)
    missing = client.get(f"/sources/{absent['id']}").json()
    assert missing["archive_url"] is None
    assert missing["verification_status"] == "unverified"
    rows = client.get(f"/sources/{absent['id']}/checks").json()
    assert any(row["checker_name"] == "wayback" and row["result"] == "not_archived" for row in rows)


def test_save_page_now_is_off_unless_configured_and_successful():
    headers, _user_id = _user()
    source = _source(headers, "Save target", "https://example.gov/save-me", document="save target", source_type="government_record")
    calls = FakeTransport([
        (lambda method, url: "web.archive.org/save/" in url, HttpResponse(
            status=200,
            url="https://web.archive.org/web/20240101000000/https://example.gov/save-me",
            body=b"saved",
            content_type="text/html",
        )),
        (lambda method, url: url.startswith("https://example.gov/save-me"), text_response(200, "page", "https://example.gov/save-me")),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
        (lambda method, url: "api.openalex.org" in url, json_response(200, {"results": []})),
    ])
    set_transport(calls)
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    assert not any("web.archive.org/save/" in url for _method, url in calls.calls)
    settings.factcheck_save_page_now = True
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    rows = client.get(f"/sources/{source['id']}/checks").json()
    assert any(row["checker_name"] == "save_page_now" and row["result"] == "archived" and row["archive_url"] for row in rows)


def test_quote_not_found_lowers_support_and_does_not_refute():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "Shoreline table", "https://example.gov/quote", document="quote page", source_type="peer_reviewed")
    claim = _debate_claim("The table says the shoreline rose by a meter.")
    _link(claim["id"], source["id"], excerpt="the shoreline rose by a meter")
    _review(headers, source["id"])
    set_transport(FakeTransport([
        (lambda method, url: url.startswith("https://example.gov/quote"), text_response(200, "<p>The table lists rainfall only.</p>", "https://example.gov/quote")),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
        (lambda method, url: "api.openalex.org" in url, json_response(200, {"results": []})),
    ]))
    rows = client.post(f"/sources/{source['id']}/checks", headers=headers).json()
    assert any(row["result"] == "quote_not_found" for row in rows)
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()
    assert summary["confidence"]["label"] != "Supported"
    assert summary["confidence"]["label"] != "Rated"
    assert summary["confidence"]["label"] != "Unsupported"
    assert not (summary["confidence"]["confidence_score"] or 0) > 0
    flagged = client.get(f"/debates/{claim['debate_id']}/claims").json()[0]
    assert flagged["needs_review"] is True


def test_inaccessible_text_is_not_treated_as_a_missing_quote():
    headers, _user_id = _user()
    source = _source(headers, "Paywalled study", "https://example.edu/paywall", document="paywall")
    claim = _debate_claim("The study reported the measurement.")
    _link(claim["id"], source["id"], excerpt="the study reported the measurement exactly")
    set_transport(FakeTransport([
        (lambda method, url: url.startswith("https://example.edu/paywall"), text_response(403, "subscribe", "https://example.edu/paywall")),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
        (lambda method, url: "api.openalex.org" in url, json_response(200, {"results": []})),
    ]))
    rows = client.post(f"/sources/{source['id']}/checks", headers=headers).json()
    assert any(row["result"] == "text_not_accessible" for row in rows)
    assert not any(row["result"] == "quote_not_found" for row in rows)


def test_related_work_stays_a_candidate_and_a_review_is_only_a_suggestion():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "Primary measurement", "https://doi.org/10.1000/primary")
    claim = _debate_claim("The primary measurement found an increase.")
    _link(claim["id"], source["id"])
    _review(headers, source["id"])
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/primary", "Primary measurement")),
        (lambda method, url: "api.openalex.org/works?search=" in url, json_response(200, {"results": [{
            "id": "https://openalex.org/W9",
            "display_name": "A systematic review of the measurement",
            "type": "article",
        }, {
            "id": "https://openalex.org/W8",
            "display_name": "Expression of concern regarding the measurement",
            "type": "article",
        }]})),
        (lambda method, url: "esearch" in url, json_response(200, {"esearchresult": {"idlist": []}})),
    ]))
    before = client.get(f"/claims/{claim['id']}/evidence-summary").json()
    rows = client.post(f"/claims/{claim['id']}/checks", headers=headers).json()
    after = client.get(f"/claims/{claim['id']}/evidence-summary").json()
    assert before["confidence"]["label"] == "Weakly supported"
    assert after["confidence"]["label"] == "Weakly supported"
    assert any(row["result"] == "possible_corroboration" and "Systematic review" in row["detail"] for row in rows)
    assert any(row["result"] == "possible_counterevidence" for row in rows)
    assert any(flag["kind"] == "consensus_suggestion" for flag in after["scope_flags"])
    queue = client.get("/factcheck/queue", headers=headers).json()
    assert any(row["result"] == "possible_counterevidence" for row in queue)
    assert not any(row["result"] == "possible_corroboration" and "Primary measurement" == row["detail"] for row in queue)


def test_llm_rating_is_kept_only_when_the_quote_is_in_the_fetched_text():
    kept = validate_llm_assessment({"rating": "supports", "quote": "rose by one meter"}, "The gauge rose by one meter.")
    assert kept["result"] == "supports"
    discarded = validate_llm_assessment({"rating": "does not support", "quote": "a sentence that was not fetched"}, "The gauge rose by one meter.")
    assert discarded["result"] == "cannot_tell"
    assert "discarded" in discarded["detail"]
    headers, _user_id = _user()
    source = _source(headers, "Gauge study", "https://example.edu/gauge", document="gauge")
    claim = _debate_claim("The gauge rose by one meter.")
    _link(claim["id"], source["id"])
    settings.factcheck_llm_base_url = "https://llm.example/v1"
    settings.factcheck_llm_api_key = "test-key"
    settings.factcheck_llm_model = "test-model"
    completion = {
        "id": "chatcmpl-1",
        "choices": [{"message": {"content": json.dumps({"rating": "supports", "quote": "rose by one meter"})}}],
    }
    set_transport(FakeTransport([
        (lambda method, url: url.startswith("https://example.edu/gauge"), text_response(200, "The gauge rose by one meter.", "https://example.edu/gauge")),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
        (lambda method, url: "api.openalex.org" in url, json_response(200, {"results": []})),
        (lambda method, url: "esearch" in url, json_response(200, {"esearchresult": {"idlist": []}})),
        (lambda method, url: url.startswith("https://llm.example"), json_response(200, completion)),
    ]))
    rows = client.post(f"/claims/{claim['id']}/checks", headers=headers).json()
    model = next(row for row in rows if row["checker_name"] == "llm")
    assert model["result"] == "supports"
    assert model["matched_snippet"] == "rose by one meter"
    assert model["response_id"] == "chatcmpl-1"


def test_official_record_adapters_do_not_treat_a_refusal_as_missing():
    headers, _user_id = _user()
    register = _source(
        headers,
        "Federal Register notice",
        "https://www.federalregister.gov/documents/2024/01/02/2024-12345/notice",
        document="Federal Register 2024-12345",
        source_type="government_record",
    )
    package = _source(
        headers,
        "govinfo package",
        "https://www.govinfo.gov/app/details/FR-2024-01-02",
        document="govinfo package FR-2024-01-02",
        source_type="government_record",
    )
    opinion = _source(
        headers,
        "Court opinion",
        "https://www.courtlistener.com/opinion/999/",
        document="opinion 999",
        source_type="primary_law",
    )
    set_transport(FakeTransport([
        (lambda method, url: "federalregister.gov/api" in url, json_response(200, {"title": "Notice", "document_number": "2024-12345"})),
        (lambda method, url: "api.govinfo.gov" in url, json_response(403, {"detail": "forbidden"})),
        (lambda method, url: "courtlistener.com" in url, json_response(401, {"detail": "no token"})),
        (lambda method, url: "api.openalex.org" in url, json_response(200, {"results": []})),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
    ]))
    register_rows = client.post(f"/sources/{register['id']}/checks", headers=headers).json()
    assert any(row["checker_name"] == "federal_register" and row["result"] == "found" for row in register_rows)
    package_rows = client.post(f"/sources/{package['id']}/checks", headers=headers).json()
    govinfo = next(row for row in package_rows if row["checker_name"] == "govinfo")
    assert govinfo["result"] == "check_failed"
    assert govinfo["http_status"] == 403
    opinion_rows = client.post(f"/sources/{opinion['id']}/checks", headers=headers).json()
    court = next(row for row in opinion_rows if row["checker_name"] == "courtlistener")
    assert court["result"] == "check_failed"
    assert "not a finding" in court["detail"]


def test_queue_is_idempotent_and_the_worker_uses_the_injected_client():
    headers, user_id = _user()
    source = _source(headers, "Queued study", "https://doi.org/10.1000/queued")
    with SessionLocal() as db:
        first = enqueue_verification(db, "source", source["id"], user_id)
        second = enqueue_verification(db, "source", source["id"], user_id)
        db.commit()
        job_id = first.id
        assert second.id == first.id
    transport = FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/queued", "Queued study")),
    ])
    process_verification_job(job_id, transport=transport)
    with SessionLocal() as db:
        job = db.get(VerificationJob, job_id)
        assert job.status == "completed"
        count = db.query(SourceCheck).filter(SourceCheck.source_id == source["id"]).count()
        again = enqueue_verification(db, "source", source["id"], user_id)
        db.commit()
        assert again.id != job_id
    process_verification_job(job_id, transport=transport)
    with SessionLocal() as db:
        assert db.query(SourceCheck).filter(SourceCheck.source_id == source["id"]).count() == count
    queue = client.get("/factcheck/queue", headers=headers)
    assert queue.status_code == 200


def test_verified_requires_a_passing_check():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "Unchecked study", "https://doi.org/10.1000/unchecked")
    blocked = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "source",
            "subject_id": source["id"],
            "result_status": "verified",
            "method": "Read it",
            "archive_url": "https://example.edu/archive/unchecked",
        },
    )
    assert blocked.status_code == 409
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/unchecked", "Unchecked study")),
    ]))
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    allowed = client.post(
        "/verification-events",
        headers=headers,
        json={
            "subject_type": "source",
            "subject_id": source["id"],
            "result_status": "verified",
            "method": "Read the Crossref record and the PDF",
            "archive_url": "https://example.edu/archive/unchecked",
        },
    )
    assert allowed.status_code == 201, allowed.text


def test_transport_sends_a_contact_user_agent_retries_and_caches(monkeypatch):
    calls = []

    def fake_request(method, url, headers=None, content=None, timeout=None, follow_redirects=None):
        calls.append((method, url, headers, timeout))
        status = 503 if len(calls) == 1 else 200
        return httpx.Response(status, json={"ok": True}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    transport = HttpxTransport(interval=0, retries=1)
    first = transport.request("GET", "https://api.crossref.org/works/10.1000/cache")
    second = transport.request("GET", "https://api.crossref.org/works/10.1000/cache")
    assert first.status == 200
    assert second.status == 200
    assert len(calls) == 2
    assert "mailto:" in calls[0][2]["User-Agent"]
    assert calls[0][2]["User-Agent"] == user_agent()
    assert get_transport() is not transport


def test_workspace_shows_the_verification_panel():
    script = open("app/static/app.js", encoding="utf-8").read()
    page = open("app/static/index.html", encoding="utf-8").read()
    assert "Re-run checks" in script
    assert "Verification queue" in page
    assert "Automated lookup of cited sources is not implemented" not in script
    assert "app.js?v=22" in page
    assert "Source #" in script and "Existence" in script and "Archive" in script


def test_url_fetch_beats_a_weak_openalex_title_match():
    headers, _user_id = _user()
    source = _source(headers, "Agency table", f"https://example.gov/table-{next(_seq)}", document="table", source_type="government_record")
    with SessionLocal() as db:
        db.add(SourceCheck(
            source_id=source["id"],
            checker_name="openalex",
            checker_version="factcheck-v1",
            api_name="api.openalex.org",
            query="works search Agency table",
            result="low_confidence",
            match_score=0.1,
            detail="OpenAlex returned a weak title match. It is not confirmed and needs review.",
        ))
        db.add(SourceCheck(
            source_id=source["id"],
            checker_name="url",
            checker_version="factcheck-v1",
            api_name="example.gov",
            query=source["url"],
            result="fetched",
            http_status=200,
            detail="HTTP 200 from the cited URL.",
        ))
        db.commit()
        assert findability_for_source(db, source["id"]) == "found"


def test_matching_quote_on_a_confirmed_doi_scores_above_zero_and_can_be_supported():
    headers, _user_id = _user()
    source = _source(headers, "Measured shoreline", "https://doi.org/10.1000/quoted")
    claim = _debate_claim("Ioannidis wrote that most published findings are false.", role="attribution")
    _link(claim["id"], source["id"], excerpt="the shoreline rose by one meter")
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/quoted", "Measured shoreline")),
        (lambda method, url: url.startswith("https://doi.org/10.1000/quoted"), text_response(
            200, "<p>The paper says the shoreline rose by one meter.</p>", "https://doi.org/10.1000/quoted",
        )),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
    ]))
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()["confidence"]
    assert summary["confidence_score"] >= 0.6
    assert summary["label"] == "Supported"
    assert summary["attribution_verified"] is True
    assert "not a finding that the claim is true" in (summary["attribution_note"] or "")
    assert "automated check" in summary["automated_source_check_detail"]
    panel = client.get(f"/claims/{claim['id']}/checks").json()
    assert any(row["checker_name"] == "crossref" and row["result"] == "found" for row in panel)
    assert any(row["checker_name"] == "metadata" and row["result"] == "found" for row in panel)


def test_substantive_claim_is_not_supported_by_one_quote():
    headers, _user_id = _user()
    source = _source(headers, "Measured shoreline", "https://doi.org/10.1000/substantive")
    claim = _debate_claim("Most published findings are false.", role="substantive")
    _link(claim["id"], source["id"], excerpt="the shoreline rose by one meter")
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/substantive", "Measured shoreline")),
        (lambda method, url: url.startswith("https://doi.org/10.1000/substantive"), text_response(
            200, "<p>The paper says the shoreline rose by one meter.</p>", "https://doi.org/10.1000/substantive",
        )),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
    ]))
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()["confidence"]
    assert summary["attribution_verified"] is True
    assert summary["label"] != "Supported"
    assert summary["confidence_score"] is None or summary["confidence_score"] < 0.6


def test_low_score_is_not_labeled_supported(monkeypatch):
    monkeypatch.setattr(settings, "support_score_threshold", 0.6)
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "One agency table", f"https://example.gov/one-table-{next(_seq)}", source_type="government_record")
    claim = _debate_claim("The agency published one figure.")
    _link(claim["id"], source["id"])
    _review(headers, source["id"])
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()["confidence"]
    assert 0 < summary["confidence_score"] < 0.6
    assert summary["label"] == "Weakly supported"
    assert summary["support_threshold"] == 0.6


def test_off_topic_related_work_is_not_stored_as_a_lead():
    headers, _user_id = _user()
    source = _source(headers, "Ioannidis essay", "https://doi.org/10.1000/ioannidis")
    claim = _debate_claim("Most published research findings are false.")
    _link(claim["id"], source["id"])
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/ioannidis", "Ioannidis essay")),
        (lambda method, url: "api.openalex.org/works?search=" in url, json_response(200, {"results": [
            {"id": "https://openalex.org/W-eeg", "display_name": "EEG practice guidelines", "type": "article", "relevance_score": 80},
            {"id": "https://openalex.org/W-esteem", "display_name": "Self-esteem measurement", "type": "article", "relevance_score": 70},
            {"id": "https://openalex.org/W-gwas", "display_name": "GWAS power calculations", "type": "article", "relevance_score": 60},
            {"id": "https://openalex.org/W-hit", "display_name": "Why most published research findings are false", "type": "article", "relevance_score": 40},
        ]})),
        (lambda method, url: "esearch" in url, json_response(200, {"esearchresult": {"idlist": []}})),
    ]))
    rows = client.post(f"/claims/{claim['id']}/checks", headers=headers).json()
    leads = [row for row in rows if row["checker_name"] == "related_work"]
    assert len(leads) == 1
    assert "findings are false" in leads[0]["detail"]
    assert "Topic match:" in leads[0]["detail"]
    assert leads[0]["result"] == "possible_corroboration"
    assert not any("EEG" in row["detail"] or "esteem" in row["detail"] or "GWAS" in row["detail"] for row in leads)


def test_needs_review_clears_when_the_record_is_found():
    headers, _user_id = _user()
    source = _source(headers, "Measured shoreline", "https://doi.org/10.1000/cleared")
    claim = _debate_claim("The paper recorded the shoreline.", role="attribution")
    _link(claim["id"], source["id"], excerpt="the shoreline rose by one meter")
    from app.models.claim import Claim

    with SessionLocal() as db:
        row = db.get(Claim, claim["id"])
        row.needs_review = True
        row.needs_review_reasons = '["no_record"]'
        db.commit()
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/cleared", "Measured shoreline")),
        (lambda method, url: url.startswith("https://doi.org/10.1000/cleared"), text_response(
            200, "<p>The paper says the shoreline rose by one meter.</p>", "https://doi.org/10.1000/cleared",
        )),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
    ]))
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    stored = client.get(f"/debates/{claim['debate_id']}/claims").json()[0]
    assert "no_record" not in stored["needs_review_reasons"]
    assert stored["needs_review"] is False


def test_on_demand_check_is_an_auditable_job():
    headers, _user_id = _user()
    source = _source(headers, "Audit study", "https://doi.org/10.1000/audit-job")
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/audit-job", "Audit study")),
    ]))
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    jobs = client.get("/factcheck/jobs", headers=headers).json()
    match = [job for job in jobs if job["subject_type"] == "source" and job["subject_id"] == source["id"] and job.get("status") == "completed"]
    assert match


def test_invalidation_actor_backfill_uses_the_recorded_user():
    from app.models.auth import User
    from app.models.evidence import Source
    from app.services.factcheck.backfill import backfill_invalidation_actors

    headers, user_id = _user()
    source = _source(headers, "Backfill source", f"https://example.edu/backfill-{next(_seq)}")
    with SessionLocal() as db:
        notice = Source(title="Backfill notice", document_reference=f"backfill-{next(_seq)}")
        db.add(notice)
        db.flush()
        row = UpstreamInvalidation(
            subject_type="source",
            subject_id=source["id"],
            kind="retraction",
            reason="Recorded before actor was stored.",
            source_id=notice.id,
            recorded_by_user_id=user_id,
            actor=None,
        )
        db.add(row)
        db.commit()
        row_id = row.id
        backfill_invalidation_actors(db.get_bind())
        db.expire_all()
        stored = db.get(UpstreamInvalidation, row_id)
        assert stored.actor == f"user:{user_id}"
        assert db.get(User, user_id) is not None


def test_absent_quote_on_a_confirmed_doi_does_not_reach_supported():
    headers, _user_id = _user()
    source = _source(headers, "Measured shoreline", "https://doi.org/10.1000/unquoted")
    claim = _debate_claim("The paper says the shoreline fell.")
    _link(claim["id"], source["id"], excerpt="the shoreline fell by a meter")
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, _crossref("10.1000/unquoted", "Measured shoreline")),
        (lambda method, url: url.startswith("https://doi.org/10.1000/unquoted"), text_response(
            200, "<p>The paper says the shoreline rose by one meter.</p>", "https://doi.org/10.1000/unquoted",
        )),
        (lambda method, url: "wayback/available" in url, json_response(200, {"archived_snapshots": {}})),
    ]))
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()["confidence"]
    assert summary["label"] != "Supported"
    assert summary["label"] != "Unsupported"
    assert not (summary["confidence_score"] or 0) > 0
    flagged = client.get(f"/debates/{claim['debate_id']}/claims").json()[0]
    assert flagged["needs_review"] is True


def test_fake_doi_is_unsupported_at_zero():
    headers, _user_id = _user()
    source = _source(headers, "Never published", "https://doi.org/10.1000/fake-paper")
    claim = _debate_claim("The fake paper measured the shoreline.")
    _link(claim["id"], source["id"], excerpt="the shoreline rose by one meter")
    set_transport(FakeTransport([
        (lambda method, url: "api.crossref.org" in url, json_response(404, {"status": "404"})),
    ]))
    client.post(f"/sources/{source['id']}/checks", headers=headers)
    summary = client.get(f"/claims/{claim['id']}/evidence-summary").json()["confidence"]
    assert summary["label"] == "Unsupported"
    assert summary["confidence_score"] == 0
    assert summary["cited_source_note"] == "cited source: no record found"


def test_worker_retraction_uses_the_crossref_title_and_a_system_actor():
    headers, _user_id = _user(UserRole.moderator)
    source = _source(headers, "Retracted shoreline study", "https://doi.org/10.1000/sys-retract")
    claim = _debate_claim("The retracted study measured the shoreline.")
    _link(claim["id"], source["id"])
    with SessionLocal() as db:
        job = (
            db.query(VerificationJob)
            .filter(VerificationJob.subject_type == "source", VerificationJob.subject_id == source["id"], VerificationJob.status == "queued")
            .one()
        )
        job.requested_by_user_id = None
        db.commit()
        job_id = job.id
    transport = FakeTransport([
        (lambda method, url: "10.1000/sys-notice" in url, _crossref(
            "10.1000/sys-notice", "Retraction of the shoreline study", author="Journal",
        )),
        (lambda method, url: "api.crossref.org" in url, _crossref(
            "10.1000/sys-retract",
            "Retracted shoreline study",
            notices=[{"type": "retraction", "DOI": "10.1000/sys-notice", "label": "Retraction"}],
        )),
    ])
    process_verification_job(job_id, transport=transport)
    record = client.get(f"/sources/{source['id']}/record").json()
    assert record["track_factor"] == 0
    assert record["retracted"] >= 1
    with SessionLocal() as db:
        invalidation = (
            db.query(UpstreamInvalidation)
            .filter(UpstreamInvalidation.subject_type == "source", UpstreamInvalidation.subject_id == source["id"])
            .one()
        )
        assert invalidation.actor == "system:factcheck"
        notice = db.query(__import__("app.models.evidence", fromlist=["Source"]).Source).filter(
            __import__("app.models.evidence", fromlist=["Source"]).Source.url == "https://doi.org/10.1000/sys-notice"
        ).one()
        assert notice.title == "Retraction of the shoreline study"
        invalidation_id = invalidation.id
    reversed_row = client.post(
        f"/library/invalidations/{invalidation_id}/reverse",
        headers=headers,
        json={"reason": "The notice concerns a different study."},
    )
    assert reversed_row.status_code == 200, reversed_row.text
    after = client.get(f"/sources/{source['id']}/record").json()
    assert after["retracted"] == 0
    assert after["track_factor"] is None


def test_http_during_a_check_does_not_hold_the_sqlite_writer():
    headers, _user_id = _user()
    source = _source(headers, "Lock study", "https://doi.org/10.1000/lock-study")
    started = threading.Event()
    wrote = threading.Event()

    def request(method, url, headers=None, data=None):
        if "api.crossref.org" in url:
            started.set()
            assert wrote.wait(2), "a second writer could not commit while the lookup was in flight"
            return _crossref("10.1000/lock-study", "Lock study")
        return HttpResponse(status=None, url=url, body=b"", content_type="", error="no route")

    def other_writer():
        assert started.wait(2)
        db = SessionLocal()
        db.add(SourceCheck(
            source_id=source["id"],
            checker_name="probe",
            checker_version="factcheck-v1",
            api_name="probe",
            query=f"lock-probe-{source['id']}",
            result="check_failed",
            detail="Concurrent write during HTTP.",
        ))
        commit_with_retry(db)
        db.close()
        wrote.set()

    thread = threading.Thread(target=other_writer)
    thread.start()
    set_transport(type("Transport", (), {"request": staticmethod(request)})())
    checked = client.post(f"/sources/{source['id']}/checks", headers=headers)
    thread.join()
    assert checked.status_code == 200, checked.text
    assert wrote.is_set()


def test_concurrent_sqlite_writes_retry_instead_of_failing_locked():
    errors = []

    def write(index):
        for step in range(6):
            db = SessionLocal()
            try:
                db.add(SourceCheck(
                    checker_name="probe",
                    checker_version="factcheck-v1",
                    api_name="probe",
                    query=f"concurrent-{index}-{step}",
                    result="check_failed",
                    detail="concurrency",
                ))
                commit_with_retry(db)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                db.close()

    threads = [threading.Thread(target=write, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_oversized_response_is_not_written_into_the_cache(monkeypatch):
    def fake_request(method, url, headers=None, content=None, timeout=None, follow_redirects=None):
        body = b'{"results":' + (b"x" * 40000)
        return httpx.Response(200, content=body, headers={"content-type": "application/json"}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    transport = HttpxTransport(interval=0, retries=0)
    url = "https://api.openalex.org/works?search=oversized-cache-body"
    result = transport.request("GET", url)
    assert result.status == 200
    with SessionLocal() as db:
        assert db.query(FactcheckCache).filter(FactcheckCache.url == url).count() == 0


@pytest.mark.skipif(os.environ.get("EPIC_LIVE_FACTCHECK") != "1", reason="Set EPIC_LIVE_FACTCHECK=1 to call Crossref")
def test_live_crossref_smoke():
    transport = HttpxTransport(interval=0, retries=1)
    response = transport.request("GET", "https://api.crossref.org/works/10.1038/171737a0")
    assert response.status == 200
    assert b"Molecular Structure of Nucleic Acids" in response.body
