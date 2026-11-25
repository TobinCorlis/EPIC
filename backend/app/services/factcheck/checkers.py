"""Public-API adapters. Each one returns audit drafts and does not write rows.

A network error is check_failed. A 404 from an identifier lookup is not_found.
A weak title match is low_confidence and is never auto-confirmed.
"""
from __future__ import annotations

import json
from urllib.parse import quote

from app.core.config import settings
from app.services.factcheck.http import CHECKER_VERSION, HttpResponse
from app.services.factcheck.text import (
    author_matches,
    content_hash,
    extract_text,
    field_matches,
    jaccard,
    quote_match,
)

CROSSREF = "api.crossref.org"
PUBMED = "eutils.ncbi.nlm.nih.gov"
OPENALEX = "api.openalex.org"
WAYBACK = "archive.org"
FEDERAL_REGISTER = "www.federalregister.gov"
GOVINFO = "api.govinfo.gov"
COURTLISTENER = "www.courtlistener.com"


def _draft(**kwargs) -> dict:
    row = {
        "checker_version": CHECKER_VERSION,
        "match_score": None,
        "http_status": None,
        "final_url": None,
        "content_type": None,
        "content_hash": None,
        "evidence_url": None,
        "archive_url": None,
        "archive_timestamp": None,
        "matched_snippet": None,
        "response_id": None,
        "detail": "",
        "claim_id": None,
        "citation_id": None,
    }
    row.update(kwargs)
    return row


def _loads(response: HttpResponse) -> dict | None:
    if response.error or response.status is None:
        return None
    try:
        payload = json.loads(response.body.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _failed(name: str, api: str, query: str, response: HttpResponse, detail: str) -> dict:
    return _draft(
        checker_name=name,
        api_name=api,
        query=query,
        result="check_failed",
        http_status=response.status,
        final_url=response.url,
        detail=detail,
    )


def _people(authors: list | None) -> str:
    names = []
    for author in authors or []:
        if not isinstance(author, dict):
            continue
        family = author.get("family") or ""
        given = author.get("given") or ""
        display = author.get("display_name") or author.get("name") or ""
        names.append(" ".join(part for part in (given, family, display) if part))
    return " ".join(names)


def metadata_result(entered: dict, recorded: dict) -> tuple[str, str]:
    """Compare title, authors, year, and journal. Missing entered fields are not failures."""
    mismatches = []
    if not field_matches(entered.get("title"), recorded.get("title")):
        mismatches.append("title")
    if not author_matches(entered.get("author"), recorded.get("author")):
        mismatches.append("authors")
    entered_year = entered.get("year")
    if entered_year and str(entered_year) != str(recorded.get("year") or ""):
        mismatches.append("year")
    if not field_matches(entered.get("journal"), recorded.get("journal"), 0.5):
        mismatches.append("journal")
    if mismatches:
        return "mismatch", "The record exists, and these entered fields do not match it: " + ", ".join(mismatches) + "."
    return "found", "Title, authors, year, and journal match the fields that were entered."


def crossref_checks(transport, doi: str, entered: dict) -> list[dict]:
    query = f"works/{doi}"
    url = f"https://api.crossref.org/works/{quote(doi, safe='/')}"
    response = transport.request("GET", url)
    if response.error or response.status is None:
        return [_failed("crossref", CROSSREF, query, response, f"Crossref could not be reached. {response.error or ''}".strip())]
    if response.status == 404:
        return [_draft(
            checker_name="crossref",
            api_name=CROSSREF,
            query=query,
            result="not_found",
            http_status=404,
            final_url=response.url,
            detail="Crossref has no work for this DOI.",
            evidence_url=f"https://doi.org/{doi}",
        )]
    payload = _loads(response)
    message = (payload or {}).get("message") if payload else None
    if response.status != 200 or not isinstance(message, dict):
        return [_failed("crossref", CROSSREF, query, response, f"Crossref returned HTTP {response.status}.")]
    title = " ".join(message.get("title") or [])
    container = " ".join(message.get("container-title") or [])
    issued = ((message.get("issued") or {}).get("date-parts") or [[None]])[0]
    year = issued[0] if issued else None
    recorded = {"title": title, "author": _people(message.get("author")), "year": year, "journal": container}
    meta_result, meta_detail = metadata_result(entered, recorded)
    rows = [_draft(
        checker_name="crossref",
        api_name=CROSSREF,
        query=query,
        result="found",
        http_status=response.status,
        final_url=response.url,
        response_id=str(message.get("DOI") or doi),
        evidence_url=f"https://doi.org/{doi}",
        detail="Crossref has this DOI.",
    ), _draft(
        checker_name="metadata",
        api_name=CROSSREF,
        query=query,
        result=meta_result,
        response_id=str(message.get("DOI") or doi),
        detail=meta_detail,
        evidence_url=f"https://doi.org/{doi}",
    )]
    rows.extend(_crossref_notices(message, query))
    return rows


def _notice_result(kind: str) -> str | None:
    folded = kind.casefold()
    if "retract" in folded:
        return "retracted"
    if "concern" in folded:
        return "expression_of_concern"
    if "correct" in folded or "erratum" in folded:
        return "corrected"
    return None


def _crossref_notices(message: dict, query: str) -> list[dict]:
    found: list[tuple[str, str | None]] = []
    for item in message.get("update-to") or []:
        if isinstance(item, dict):
            found.append((str(item.get("type") or item.get("label") or ""), item.get("DOI") or item.get("id")))
    for key, items in (message.get("relation") or {}).items():
        if _notice_result(str(key)) is None:
            continue
        for item in items or []:
            if isinstance(item, dict):
                found.append((str(key), item.get("id") or item.get("DOI")))
    rows = []
    seen = set()
    for kind, notice_id in found:
        result = _notice_result(kind)
        if result is None or (result, notice_id) in seen:
            continue
        seen.add((result, notice_id))
        notice = str(notice_id or "")
        rows.append(_draft(
            checker_name="retraction" if result == "retracted" else "notice",
            api_name=CROSSREF,
            query=query,
            result=result,
            response_id=notice or None,
            evidence_url=f"https://doi.org/{notice}" if notice.startswith("10.") else None,
            detail=f"Crossref relation '{kind}'." + (f" Notice DOI {notice}." if notice else ""),
        ))
    return rows


def pubmed_checks(transport, pmid: str, entered: dict) -> list[dict]:
    email = quote(settings.factcheck_contact_email)
    query = f"esummary pubmed {pmid}"
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&id={quote(pmid)}&retmode=json&tool=epic&email={email}"
    )
    response = transport.request("GET", url)
    if response.error or response.status is None:
        return [_failed("pubmed", PUBMED, query, response, f"PubMed could not be reached. {response.error or ''}".strip())]
    payload = _loads(response) or {}
    record = (payload.get("result") or {}).get(pmid)
    if response.status == 404 or not isinstance(record, dict) or record.get("error"):
        return [_draft(
            checker_name="pubmed",
            api_name=PUBMED,
            query=query,
            result="not_found",
            http_status=response.status,
            final_url=response.url,
            detail="PubMed has no record for this PMID.",
            evidence_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}",
        )]
    if response.status != 200:
        return [_failed("pubmed", PUBMED, query, response, f"PubMed returned HTTP {response.status}.")]
    authors = " ".join(
        author.get("name", "") for author in record.get("authors") or [] if isinstance(author, dict)
    )
    year = str(record.get("sortpubdate") or record.get("pubdate") or "")[:4]
    recorded = {
        "title": record.get("title") or "",
        "author": authors,
        "year": year or None,
        "journal": record.get("fulljournalname") or record.get("source") or "",
    }
    meta_result, meta_detail = metadata_result(entered, recorded)
    pubtypes = [str(item) for item in record.get("pubtype") or []]
    rows = [_draft(
        checker_name="pubmed",
        api_name=PUBMED,
        query=query,
        result="found",
        http_status=response.status,
        final_url=response.url,
        response_id=pmid,
        evidence_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}",
        detail="PubMed has this PMID.",
    ), _draft(
        checker_name="metadata",
        api_name=PUBMED,
        query=query,
        result=meta_result,
        response_id=pmid,
        detail=meta_detail,
        evidence_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}",
    )]
    for pubtype in pubtypes:
        result = _notice_result(pubtype)
        if result is None:
            continue
        rows.append(_draft(
            checker_name="retraction" if result == "retracted" else "notice",
            api_name=PUBMED,
            query=query,
            result=result,
            response_id=pmid,
            evidence_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}",
            detail=f"PubMed publication type '{pubtype}'.",
        ))
    return rows


def openalex_checks(transport, title: str, author: str | None) -> list[dict]:
    email = quote(settings.factcheck_contact_email)
    query = f"works search {title}"
    url = f"https://api.openalex.org/works?search={quote(title)}&per-page=5&mailto={email}"
    response = transport.request("GET", url)
    if response.error or response.status is None or response.status != 200:
        detail = response.error or f"OpenAlex returned HTTP {response.status}."
        return [_failed("openalex", OPENALEX, query, response, f"OpenAlex could not be searched. {detail}")]
    payload = _loads(response) or {}
    results = payload.get("results") or []
    if not results:
        return [_draft(
            checker_name="openalex",
            api_name=OPENALEX,
            query=query,
            result="not_found",
            http_status=response.status,
            final_url=response.url,
            detail="OpenAlex returned no work for this title.",
        )]
    best = None
    best_score = -1.0
    for work in results:
        if not isinstance(work, dict):
            continue
        score = jaccard(title, work.get("display_name") or "")
        if score > best_score:
            best = work
            best_score = score
    if best is None:
        return [_draft(
            checker_name="openalex",
            api_name=OPENALEX,
            query=query,
            result="not_found",
            http_status=response.status,
            detail="OpenAlex returned no usable work.",
        )]
    names = " ".join(
        ((item.get("author") or {}).get("display_name") or "")
        for item in best.get("authorships") or []
        if isinstance(item, dict)
    )
    confirmed = best_score >= 0.72 and author_matches(author, names)
    work_id = str(best.get("id") or "")
    return [_draft(
        checker_name="openalex",
        api_name=OPENALEX,
        query=query,
        result="found" if confirmed else "low_confidence",
        match_score=round(best_score, 2),
        http_status=response.status,
        final_url=response.url,
        response_id=work_id or None,
        evidence_url=work_id or None,
        detail=(
            "OpenAlex title and author match the entered source."
            if confirmed
            else "OpenAlex returned a weak title match. It is not confirmed and needs review."
        ),
    )]


def url_check(transport, url: str) -> tuple[dict, bytes, str]:
    response = transport.request("GET", url)
    if response.error or response.status is None:
        return (
            _failed("url", urlparse_host(url), url, response, f"The URL could not be fetched. {response.error or ''}".strip()),
            b"",
            "",
        )
    result = "not_found" if response.status == 404 else "fetched"
    if response.status >= 500:
        result = "check_failed"
    detail = f"HTTP {response.status} from the cited URL."
    if response.status in {401, 403}:
        detail = f"HTTP {response.status}. The page was not readable."
    row = _draft(
        checker_name="url",
        api_name=urlparse_host(url),
        query=url,
        result=result,
        http_status=response.status,
        final_url=response.url,
        content_type=response.content_type,
        content_hash=content_hash(response.body) if response.body else None,
        detail=detail,
    )
    return row, response.body, response.content_type or ""


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc or url


def wayback_check(transport, url: str) -> dict:
    query = f"wayback available {url}"
    endpoint = f"https://archive.org/wayback/available?url={quote(url, safe='')}"
    response = transport.request("GET", endpoint)
    if response.error or response.status is None or response.status != 200:
        return _failed("wayback", WAYBACK, query, response, f"The Internet Archive availability API failed. {response.error or ''}".strip())
    payload = _loads(response) or {}
    closest = ((payload.get("archived_snapshots") or {}).get("closest") or {})
    if closest.get("available") and closest.get("url"):
        return _draft(
            checker_name="wayback",
            api_name=WAYBACK,
            query=query,
            result="archived",
            http_status=response.status,
            final_url=response.url,
            archive_url=str(closest.get("url")),
            archive_timestamp=str(closest.get("timestamp") or ""),
            evidence_url=str(closest.get("url")),
            response_id=str(closest.get("timestamp") or "") or None,
            detail="The Internet Archive returned a snapshot.",
        )
    return _draft(
        checker_name="wayback",
        api_name=WAYBACK,
        query=query,
        result="not_archived",
        http_status=response.status,
        final_url=response.url,
        detail="The Internet Archive has no snapshot for this URL. Nothing was marked archived.",
    )


def save_page_check(transport, url: str) -> dict | None:
    if not settings.factcheck_save_page_now:
        return None
    query = f"save {url}"
    endpoint = f"https://web.archive.org/save/{quote(url, safe=':/')}"
    response = transport.request("POST", endpoint)
    snapshot = response.url if "web.archive.org/web/" in (response.url or "") else ""
    if not snapshot and response.body:
        text = response.body.decode("utf-8", errors="replace")
        marker = text.find("https://web.archive.org/web/")
        if marker >= 0:
            snapshot = text[marker:].split()[0].strip('"\'<>')
    if response.error or response.status is None or response.status >= 400 or not snapshot:
        row = _failed("save_page_now", WAYBACK, query, response, "Save Page Now did not return a snapshot. Nothing was recorded as archived.")
        return row
    return _draft(
        checker_name="save_page_now",
        api_name=WAYBACK,
        query=query,
        result="archived",
        http_status=response.status,
        final_url=response.url,
        archive_url=snapshot,
        evidence_url=snapshot,
        detail="Save Page Now returned a snapshot.",
    )


def _official(transport, name: str, api: str, url: str, query: str, headers: dict | None, found_detail: str, missing_detail: str) -> dict:
    response = transport.request("GET", url, headers=headers)
    if response.error or response.status is None:
        return _failed(name, api, query, response, f"{api} could not be reached. {response.error or ''}".strip())
    if response.status == 404:
        return _draft(
            checker_name=name,
            api_name=api,
            query=query,
            result="not_found",
            http_status=404,
            final_url=response.url,
            evidence_url=url,
            detail=missing_detail,
        )
    if response.status in {401, 403}:
        return _draft(
            checker_name=name,
            api_name=api,
            query=query,
            result="check_failed",
            http_status=response.status,
            final_url=response.url,
            detail=f"{api} refused the request (HTTP {response.status}). This is not a finding that the record is missing.",
        )
    if response.status != 200:
        return _failed(name, api, query, response, f"{api} returned HTTP {response.status}.")
    return _draft(
        checker_name=name,
        api_name=api,
        query=query,
        result="found",
        http_status=200,
        final_url=response.url,
        evidence_url=url,
        response_id=query,
        detail=found_detail,
    )


def federal_register_check(transport, document_number: str) -> dict:
    url = f"https://www.federalregister.gov/api/v1/documents/{quote(document_number)}.json"
    return _official(
        transport,
        "federal_register",
        FEDERAL_REGISTER,
        url,
        document_number,
        None,
        "The Federal Register has this document.",
        "The Federal Register has no document with this number.",
    )


def govinfo_check(transport, package_id: str) -> dict:
    key = quote(settings.govinfo_api_key) if settings.govinfo_api_key else ""
    suffix = f"?api_key={key}" if key else ""
    url = f"https://api.govinfo.gov/packages/{quote(package_id)}/summary{suffix}"
    return _official(
        transport,
        "govinfo",
        GOVINFO,
        url,
        package_id,
        None,
        "govinfo has this package.",
        "govinfo has no package with this id.",
    )


def courtlistener_check(transport, opinion_id: str) -> dict:
    headers = {}
    if settings.courtlistener_api_token:
        headers["Authorization"] = f"Token {settings.courtlistener_api_token}"
    url = f"https://www.courtlistener.com/api/rest/v4/opinions/{quote(opinion_id)}/"
    return _official(
        transport,
        "courtlistener",
        COURTLISTENER,
        url,
        opinion_id,
        headers or None,
        "CourtListener has this opinion.",
        "CourtListener has no opinion with this id.",
    )


def quote_checks(excerpt: str, citation_id: int, body: bytes, content_type: str, http_status: int | None) -> dict:
    if http_status in {401, 403}:
        return _draft(
            checker_name="quote",
            api_name="fetched-text",
            query=f"citation {citation_id}",
            result="text_not_accessible",
            citation_id=citation_id,
            http_status=http_status,
            detail="The page refused access. The quote was not treated as missing or as a refutation.",
        )
    text = extract_text(body, content_type)
    result, score, snippet = quote_match(excerpt, text)
    detail = {
        "quote_found": "The quoted text appears in the accessible text.",
        "quote_not_found": "The quoted text was not found in the accessible text. This lowers support and flags review. It is not a refutation.",
        "text_not_accessible": "The source text could not be read (paywall, scan, or no extractor). The quote was not treated as missing.",
    }[result]
    if snippet and result == "text_not_accessible" and snippet.startswith("The excerpt"):
        detail = snippet
        snippet = ""
    return _draft(
        checker_name="quote",
        api_name="fetched-text",
        query=f"citation {citation_id}",
        result=result,
        match_score=score,
        citation_id=citation_id,
        matched_snippet=snippet or None,
        detail=detail,
    )


def classify_related(title: str, work_type: str) -> tuple[str, str]:
    blob = f"{title} {work_type}".casefold()
    if "systematic review" in blob or "meta-analysis" in blob or "meta analysis" in blob:
        return (
            "possible_corroboration",
            "Systematic review or meta-analysis. Candidate only. It is not linked evidence and does not change the score.",
        )
    if "retract" in blob or "expression of concern" in blob:
        return (
            "possible_counterevidence",
            "Candidate counterevidence only. It is not linked evidence and does not change the score.",
        )
    return (
        "possible_corroboration",
        "Possible corroboration only. It is not linked evidence and does not change the score.",
    )


def openalex_related(transport, claim_text: str, claim_id: int) -> list[dict]:
    email = quote(settings.factcheck_contact_email)
    term = " ".join(claim_text.split())[:240]
    query = f"related {term}"
    url = f"https://api.openalex.org/works?search={quote(term)}&per-page=5&mailto={email}"
    response = transport.request("GET", url)
    if response.error or response.status != 200:
        return [_failed("related_work", OPENALEX, query, response, f"OpenAlex related search failed. {response.error or ''}".strip())]
    payload = _loads(response) or {}
    rows = []
    for work in (payload.get("results") or [])[:5]:
        if not isinstance(work, dict):
            continue
        title = str(work.get("display_name") or "")
        work_type = str(work.get("type") or "")
        result, detail = classify_related(title, work_type)
        work_id = str(work.get("id") or "")
        rows.append(_draft(
            checker_name="related_work",
            api_name=OPENALEX,
            query=query,
            result=result,
            claim_id=claim_id,
            response_id=work_id or None,
            evidence_url=work_id or None,
            detail=f"{detail} Title: {title}",
        ))
    return rows


def pubmed_related(transport, claim_text: str, claim_id: int) -> list[dict]:
    email = quote(settings.factcheck_contact_email)
    term = " ".join(claim_text.split())[:240]
    query = f"esearch {term}"
    search = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&retmode=json&retmax=5&term={quote(term)}&tool=epic&email={email}"
    )
    response = transport.request("GET", search)
    if response.error or response.status != 200:
        return [_failed("related_work", PUBMED, query, response, f"PubMed related search failed. {response.error or ''}".strip())]
    payload = _loads(response) or {}
    ids = ((payload.get("esearchresult") or {}).get("idlist") or [])[:5]
    if not ids:
        return []
    summary_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&retmode=json&id={quote(','.join(ids))}&tool=epic&email={email}"
    )
    summary = transport.request("GET", summary_url)
    if summary.error or summary.status != 200:
        return [_failed("related_work", PUBMED, query, summary, "PubMed summary for the related search failed.")]
    records = (_loads(summary) or {}).get("result") or {}
    rows = []
    for pmid in ids:
        record = records.get(pmid)
        if not isinstance(record, dict):
            continue
        title = str(record.get("title") or "")
        pubtypes = " ".join(str(item) for item in record.get("pubtype") or [])
        result, detail = classify_related(title, pubtypes)
        rows.append(_draft(
            checker_name="related_work",
            api_name=PUBMED,
            query=query,
            result=result,
            claim_id=claim_id,
            response_id=pmid,
            evidence_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}",
            detail=f"{detail} Title: {title}",
        ))
    return rows


def llm_configured() -> bool:
    return bool(settings.factcheck_llm_base_url and settings.factcheck_llm_api_key and settings.factcheck_llm_model)


def validate_llm_assessment(payload: dict, source_text: str) -> dict:
    """Keep a model rating only when its quote is present in the fetched text."""
    raw = str(payload.get("rating") or "").strip().casefold().replace("-", " ")
    rating = raw.replace(" ", "_")
    aliases = {
        "supports": "supports",
        "does_not_support": "does_not_support",
        "does_not_supports": "does_not_support",
        "partially": "partially",
        "partial": "partially",
        "cannot_tell": "cannot_tell",
    }
    if raw == "does not support":
        rating = "does_not_support"
    elif raw == "cannot tell":
        rating = "cannot_tell"
    rating = aliases.get(rating, rating)
    quote = str(payload.get("quote") or "")
    discarded = {
        "result": "cannot_tell",
        "matched_snippet": None,
        "detail": "The model assessment was discarded because its quote is not in the fetched text.",
    }
    if rating not in {"supports", "does_not_support", "partially", "cannot_tell"}:
        return discarded
    if rating == "cannot_tell":
        return {
            "result": "cannot_tell",
            "matched_snippet": None,
            "detail": "The model could not tell from the fetched text.",
        }
    if not quote or quote not in source_text:
        return discarded
    return {
        "result": rating,
        "matched_snippet": quote[:500],
        "detail": "The quote appears in the fetched text. This rating does not change the score by itself.",
    }


def llm_check(transport, claim_text: str, source_text: str, claim_id: int) -> dict | None:
    if not llm_configured() or not source_text.strip():
        return None
    prompt = {
        "instruction": (
            "Rate only whether the fetched source text supports the claim. "
            "Use supports, does_not_support, partially, or cannot_tell. "
            "The quote must be an exact span from the fetched text. Do not add facts."
        ),
        "claim": claim_text,
        "source_text": source_text[:50_000],
    }
    body = json.dumps({
        "model": settings.factcheck_llm_model,
        "messages": [{"role": "user", "content": json.dumps(prompt)}],
    }).encode()
    endpoint = settings.factcheck_llm_base_url.rstrip("/") + "/chat/completions"
    response = transport.request(
        "POST",
        endpoint,
        headers={"Authorization": f"Bearer {settings.factcheck_llm_api_key}", "Content-Type": "application/json"},
        data=body,
    )
    query = "chat/completions claim+fetched text"
    if response.error or response.status != 200:
        return _failed("llm", "factcheck-llm", query, response, "The optional model could not be reached. The deterministic checks still stand.")
    payload = _loads(response) or {}
    try:
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    verdict = validate_llm_assessment(parsed, source_text)
    return _draft(
        checker_name="llm",
        api_name="factcheck-llm",
        query=query,
        result=verdict["result"],
        claim_id=claim_id,
        matched_snippet=verdict["matched_snippet"],
        response_id=str(payload.get("id") or "") or None,
        detail=verdict["detail"],
    )
