"""Identifier parsing, text extraction, and the quote comparison.

A quote that is absent is not a refutation. Text that cannot be read is
reported as not accessible.
"""
from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import unicodedata
from difflib import SequenceMatcher

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
PMID_RE = re.compile(r"(?:pmid\s*[:#]?\s*|pubmed\.ncbi\.nlm\.nih\.gov/|pubmed/)(\d{4,9})", re.I)
FR_RE = re.compile(r"\b(20\d{2}-\d{4,6})\b")
GOVINFO_RE = re.compile(r"\b((?:USCODE|PLAW|CFR|CREC|FR)-[A-Z0-9-]+)\b", re.I)
COURT_RE = re.compile(r"courtlistener\.com/(?:opinion|api/rest/v\d+/opinions)/(\d+)", re.I)
QUOTE_FOUND_AT = 0.9


def extract_doi(*parts: str | None) -> str | None:
    blob = " ".join(part for part in parts if part)
    match = DOI_RE.search(blob)
    if not match:
        return None
    return match.group(0).rstrip(").,;")


def extract_pmid(*parts: str | None) -> str | None:
    blob = " ".join(part for part in parts if part)
    match = PMID_RE.search(blob)
    return match.group(1) if match else None


def extract_federal_register(*parts: str | None) -> str | None:
    blob = " ".join(part for part in parts if part)
    folded = blob.casefold()
    if "federalregister.gov" not in folded and "federal register" not in folded:
        return None
    match = FR_RE.search(blob)
    return match.group(1) if match else None


def extract_govinfo(*parts: str | None) -> str | None:
    blob = " ".join(part for part in parts if part)
    folded = blob.casefold()
    if "govinfo.gov" not in folded and "govinfo package" not in folded:
        return None
    match = GOVINFO_RE.search(blob)
    return match.group(1) if match else None


def extract_opinion(*parts: str | None) -> str | None:
    blob = " ".join(part for part in parts if part)
    match = COURT_RE.search(blob)
    return match.group(1) if match else None


def tokens(value: str | None) -> set[str]:
    return set(re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).split())


def jaccard(left: str | None, right: str | None) -> float:
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def field_matches(entered: str | None, recorded: str | None, threshold: float = 0.72) -> bool:
    if not (entered or "").strip():
        return True
    if not (recorded or "").strip():
        return False
    if entered.casefold() in recorded.casefold() or recorded.casefold() in entered.casefold():
        return True
    return jaccard(entered, recorded) >= threshold


def author_matches(entered: str | None, recorded: str | None) -> bool:
    if not (entered or "").strip():
        return True
    recorded_tokens = tokens(recorded)
    needed = {token for token in tokens(entered) if len(token) > 2}
    if not needed:
        return True
    return bool(needed & recorded_tokens)


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).casefold().strip()
    return text


def html_to_text(raw: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    return cleaned


def pdf_to_text(body: bytes) -> str | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if text.strip():
            return text
    except Exception:
        pass
    if shutil.which("pdftotext"):
        try:
            completed = subprocess.run(
                ["pdftotext", "-", "-"],
                input=body,
                capture_output=True,
                timeout=20,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                return completed.stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired):
            return None
    return None


def extract_text(body: bytes, content_type: str) -> str | None:
    if not body:
        return None
    if "pdf" in content_type.casefold() or body[:4] == b"%PDF":
        return pdf_to_text(body)
    raw = body.decode("utf-8", errors="replace")
    if "html" in content_type.casefold() or "<html" in raw[:800].casefold():
        return html_to_text(raw)
    return raw


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def quote_match(excerpt: str, text: str | None) -> tuple[str, float | None, str]:
    """Return result, score, and snippet. Absence is not a refutation."""
    if text is None or not text.strip():
        return "text_not_accessible", None, ""
    needle = normalize(excerpt)
    haystack = normalize(text)
    if len(needle) < 8:
        return "text_not_accessible", None, "The excerpt is too short to check."
    if needle in haystack:
        return "quote_found", 1.0, excerpt.strip()[:500]
    window = len(needle)
    best = 0.0
    snippet = ""
    step = max(1, window // 5)
    limit = min(len(haystack), 200_000)
    for index in range(0, max(1, limit - window + 1), step):
        chunk = haystack[index:index + window]
        ratio = SequenceMatcher(None, needle, chunk).ratio()
        if ratio > best:
            best = ratio
            snippet = chunk
        if best >= 0.98:
            break
    score = round(best, 2)
    if best >= QUOTE_FOUND_AT:
        return "quote_found", score, snippet[:500]
    return "quote_not_found", score, snippet[:500]
