"""Polite HTTP for public scholarly and archive APIs.

The default client times out, retries, waits between calls to one host,
sends a contact email, and caches successful text responses. Tests replace
it with set_transport and never open a socket.
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

import httpx

from app.core.clock import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.factcheck import FactcheckCache

CHECKER_VERSION = "factcheck-v1"


@dataclass
class HttpResponse:
    status: int | None
    url: str
    body: bytes
    content_type: str
    error: str | None = None


def user_agent() -> str:
    email = settings.factcheck_contact_email.strip() or "factcheck@epic.local"
    return f"EPIC-factcheck/{CHECKER_VERSION} (mailto:{email})"


class HostLimiter:
    def __init__(self, interval: float):
        self.interval = interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        if self.interval <= 0:
            return
        host = urlparse(url).netloc or url
        with self._lock:
            now = time.monotonic()
            due = self._last.get(host, 0.0) + self.interval
            delay = max(0.0, due - now)
            self._last[host] = now + delay
        if delay:
            time.sleep(delay)


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _cacheable(content_type: str) -> bool:
    kind = content_type.casefold()
    return any(token in kind for token in ("json", "html", "text", "xml"))


class HttpxTransport:
    def __init__(self, interval: float | None = None, retries: int | None = None):
        self.interval = settings.factcheck_min_interval_seconds if interval is None else interval
        self.retries = settings.factcheck_retries if retries is None else retries
        self._limiter = HostLimiter(self.interval)

    def request(self, method: str, url: str, headers: dict | None = None, data: bytes | None = None) -> HttpResponse:
        method = method.upper()
        if method == "GET":
            cached = self._read_cache(url)
            if cached is not None:
                return cached
        self._limiter.wait(url)
        outgoing = {"User-Agent": user_agent(), "Accept": "application/json, text/html, */*"}
        if headers:
            outgoing.update(headers)
        last_error = "request failed"
        attempts = self.retries + 1
        for _attempt in range(attempts):
            try:
                response = httpx.request(
                    method,
                    url,
                    headers=outgoing,
                    content=data,
                    timeout=settings.factcheck_timeout_seconds,
                    follow_redirects=True,
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue
            if response.status_code >= 500 or response.status_code == 429:
                last_error = f"HTTP {response.status_code}"
                continue
            content_type = response.headers.get("content-type", "")
            result = HttpResponse(
                status=response.status_code,
                url=str(response.url),
                body=response.content,
                content_type=content_type,
            )
            if method == "GET" and _cacheable(content_type):
                self._write_cache(url, result)
            return result
        return HttpResponse(status=None, url=url, body=b"", content_type="", error=last_error)

    def _read_cache(self, url: str) -> HttpResponse | None:
        db = SessionLocal()
        try:
            row = db.query(FactcheckCache).filter(FactcheckCache.cache_key == _cache_key(url)).one_or_none()
            if row is None or row.expires_at <= utcnow():
                return None
            return HttpResponse(
                status=row.http_status,
                url=row.final_url or url,
                body=row.body.encode(),
                content_type=row.content_type or "",
            )
        finally:
            db.close()

    def _write_cache(self, url: str, result: HttpResponse) -> None:
        db = SessionLocal()
        try:
            key = _cache_key(url)
            row = db.query(FactcheckCache).filter(FactcheckCache.cache_key == key).one_or_none()
            if row is None:
                row = FactcheckCache(cache_key=key, url=url)
                db.add(row)
            row.url = url
            row.http_status = result.status
            row.final_url = result.url
            row.content_type = result.content_type
            row.body = result.body.decode("utf-8", errors="replace")[:400_000]
            row.fetched_at = utcnow()
            row.expires_at = utcnow() + timedelta(hours=settings.factcheck_cache_hours)
            db.commit()
        finally:
            db.close()


_transport: object | None = None


def set_transport(transport) -> None:
    global _transport
    _transport = transport


def get_transport():
    if _transport is not None:
        return _transport
    return HttpxTransport()
