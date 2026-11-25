"""Referee engine. It rules only a move that was already submitted.

The default provider compares that move with lore recorded on the matchup.
It does not invent lore, citations, counters, or powers. An optional
OpenAI-compatible model is used only when its environment variables are set,
and only with the submitted move plus that lore. A reply that cites unknown
lore becomes Unverified.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.claim import Claim
from app.models.evidence import Citation, ClaimEvidence, Source
from app.models.fable import FableLoreItem, FableMatchup, FableMove, FableRuling

PROVIDER_DETERMINISTIC = "deterministic-lore"
PROVIDER_VERSION = "1"
PROVIDER_LLM = "openai-compatible"
LLM_VERSION = "1"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "the", "of", "to", "and", "or", "in", "on", "at", "for", "with",
    "his", "her", "its", "can", "is", "was", "by", "from", "that", "this",
}
_MAGNITUDE = (
    ("planet", 6),
    ("city", 4),
    ("building", 3),
    ("several", 2),
    ("single", 1),
    ("one", 1),
    ("once", 1),
)
_CONTRADICTION = ("never", "does not", "cannot", "can't")


@dataclass
class RulingDraft:
    ruling: str
    reason: str
    citation: str
    lore_item_ids: list[int]
    confidence: float
    provider_name: str
    provider_version: str


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text.casefold()) if token not in _STOP}


def _magnitude(text: str) -> int:
    folded = text.casefold()
    return max((rank for word, rank in _MAGNITUDE if word in folded), default=0)


def _contradicts(body: str) -> bool:
    folded = body.casefold()
    return any(phrase in folded for phrase in _CONTRADICTION)


def _citation(item: FableLoreItem) -> str:
    return f"{item.work_title}, {item.installment}, {item.pinpoint}"


class DeterministicLoreReferee:
    name = PROVIDER_DETERMINISTIC
    version = PROVIDER_VERSION

    def rule(self, move_text: str, claimed_source: str, lore: list[FableLoreItem], *, canon_only: bool) -> RulingDraft:
        cited = _matching_lore(claimed_source, lore)
        if not cited:
            return RulingDraft(
                "disallowed",
                "The citation does not exist in the recorded lore.",
                claimed_source,
                [],
                0.9,
                self.name,
                self.version,
            )
        if canon_only and all(item.canon_status == "non_canon" for item in cited):
            return RulingDraft(
                "disallowed",
                "The cited source is non-canon in a canon-only room.",
                _citation(cited[0]),
                [item.id for item in cited],
                0.9,
                self.name,
                self.version,
            )
        move_terms = _tokens(move_text)
        overlapping = [item for item in cited if _tokens(item.body) & move_terms]
        if not overlapping:
            return RulingDraft(
                "unverified",
                "Canon is silent on this feat. The cited lore does not address it.",
                _citation(cited[0]),
                [item.id for item in cited],
                0.4,
                self.name,
                self.version,
            )
        conflicts = [item for item in overlapping if _contradicts(item.body)]
        supports = [item for item in overlapping if not _contradicts(item.body)]
        if conflicts and supports:
            return RulingDraft(
                "unverified",
                "The recorded lore items conflict on this move.",
                _citation(supports[0]),
                [item.id for item in overlapping],
                0.45,
                self.name,
                self.version,
            )
        if conflicts and not supports:
            return RulingDraft(
                "disallowed",
                "Recorded lore contradicts the move.",
                _citation(conflicts[0]),
                [item.id for item in conflicts],
                0.85,
                self.name,
                self.version,
            )
        lore_magnitude = max(_magnitude(item.body) for item in supports)
        move_magnitude = _magnitude(move_text)
        if move_magnitude > lore_magnitude and lore_magnitude > 0:
            return RulingDraft(
                "disallowed",
                "The claimed magnitude exceeds what the cited lore records.",
                _citation(supports[0]),
                [item.id for item in supports],
                0.85,
                self.name,
                self.version,
            )
        return RulingDraft(
            "allowed",
            "A matching canon lore item supports the claim at the claimed level.",
            _citation(supports[0]),
            [item.id for item in supports],
            0.8,
            self.name,
            self.version,
        )


def _matching_lore(claimed_source: str, lore: list[FableLoreItem]) -> list[FableLoreItem]:
    text = claimed_source.casefold()
    hits = []
    for item in lore:
        title = item.work_title.casefold()
        if title and title in text:
            hits.append(item)
    return hits


def validate_llm_ruling(payload: dict, lore: list[FableLoreItem]) -> RulingDraft:
    """Accept only a schema-valid reply that cites recorded lore. Otherwise Unverified."""
    known = {item.id: item for item in lore}
    ruling = payload.get("ruling")
    raw_ids = payload.get("lore_item_ids") or []
    try:
        lore_ids = [int(item) for item in raw_ids]
    except (TypeError, ValueError):
        lore_ids = []
    reason = str(payload.get("reason") or "").strip()
    if ruling not in {"allowed", "disallowed", "unverified"} or not set(lore_ids) <= set(known) or not lore_ids or not reason:
        return RulingDraft(
            "unverified",
            "The model reply did not cite recorded lore, so the ruling is Unverified.",
            "",
            [],
            0.2,
            PROVIDER_LLM,
            LLM_VERSION,
        )
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))
    return RulingDraft(
        ruling,
        reason,
        _citation(known[lore_ids[0]]),
        lore_ids,
        confidence,
        PROVIDER_LLM,
        LLM_VERSION,
    )


class OpenAICompatibleReferee:
    """Calls a configured chat endpoint. Tests use validate_llm_ruling directly."""

    name = PROVIDER_LLM
    version = LLM_VERSION

    def rule(self, move_text: str, claimed_source: str, lore: list[FableLoreItem], *, canon_only: bool) -> RulingDraft:
        import urllib.request

        lore_payload = [
            {"id": item.id, "citation": _citation(item), "canon_status": item.canon_status, "body": item.body}
            for item in lore
        ]
        prompt = {
            "instruction": (
                "Rule only this submitted move against the recorded lore. "
                "Do not add a counter, power, or fact. Reply with JSON keys "
                "ruling, reason, lore_item_ids, confidence."
            ),
            "canon_only": canon_only,
            "move_text": move_text,
            "claimed_source": claimed_source,
            "lore": lore_payload,
        }
        body = json.dumps({
            "model": settings.referee_llm_model,
            "messages": [{"role": "user", "content": json.dumps(prompt)}],
        }).encode()
        request = urllib.request.Request(
            settings.referee_llm_base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {settings.referee_llm_api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
        content = payload["choices"][0]["message"]["content"]
        return validate_llm_ruling(json.loads(content), lore)


def llm_configured() -> bool:
    return bool(settings.referee_llm_base_url and settings.referee_llm_api_key and settings.referee_llm_model)


def get_provider():
    if llm_configured():
        return OpenAICompatibleReferee()
    return DeterministicLoreReferee()


def _store_ruling(db: Session, move: FableMove, draft: RulingDraft, status: str, user_id: int | None) -> FableRuling:
    row = FableRuling(
        move_id=move.id,
        ruling=draft.ruling,
        reason=draft.reason,
        citation=draft.citation,
        lore_item_ids=json.dumps(draft.lore_item_ids),
        confidence=draft.confidence,
        ruled_by="ai",
        provider_name=draft.provider_name,
        provider_version=draft.provider_version,
        status=status,
        created_by_user_id=user_id,
    )
    db.add(row)
    if status == "accepted":
        _apply_to_move(move, row)
    return row


def _apply_to_move(move: FableMove, row: FableRuling) -> None:
    move.ruling = row.ruling
    move.reason = row.reason
    move.citation = row.citation
    move.ruled_by = row.ruled_by
    move.ruled_by_user_id = row.created_by_user_id


def rule_submitted_moves(db: Session, matchup: FableMatchup, user_id: int | None = None) -> list[FableRuling]:
    """Rule moves that exist and have no effective ruling. Never creates a move."""
    lore = db.query(FableLoreItem).filter(FableLoreItem.matchup_id == matchup.id).all()
    moves = db.query(FableMove).filter(FableMove.matchup_id == matchup.id).order_by(FableMove.id).all()
    provider = get_provider()
    status = "accepted" if matchup.referee_mode == "ai_auto" else "proposed"
    if matchup.referee_mode == "moderator_only":
        return []
    created = []
    for move in moves:
        if move.ruling:
            continue
        draft = provider.rule(move.move_text, move.claimed_source, lore, canon_only=matchup.canon_only)
        created.append(_store_ruling(db, move, draft, status, user_id))
    return created


def accept_ruling(ruling: FableRuling, move: FableMove) -> None:
    ruling.status = "accepted"
    _apply_to_move(move, ruling)


def override_ruling(db: Session, ruling: FableRuling, move: FableMove, user_id: int, payload) -> FableRuling:
    row = FableRuling(
        move_id=move.id,
        ruling=payload.ruling,
        reason=payload.reason.strip(),
        citation=payload.citation.strip(),
        lore_item_ids=ruling.lore_item_ids,
        confidence=None,
        ruled_by="moderator",
        provider_name=None,
        provider_version=None,
        status="overridden",
        override_reason=payload.override_reason.strip(),
        created_by_user_id=user_id,
    )
    db.add(row)
    _apply_to_move(move, row)
    return row


def evidence_flags(db: Session, debate_id: int) -> list[dict]:
    """Deterministic flags from recorded links. This does not decide who is right."""
    claims = db.query(Claim).filter(Claim.debate_id == debate_id).all()
    flags = []
    for claim in claims:
        links = (
            db.query(ClaimEvidence)
            .filter(ClaimEvidence.claim_id == claim.id)
            .all()
        )
        for link in links:
            source = db.get(Source, db.get(Citation, link.citation_id).source_id) if link.citation_id else None
            if source is None:
                flags.append({
                    "claim_id": claim.id,
                    "claim_evidence_id": link.id,
                    "kind": "citation_missing",
                    "detail": "The move cites a source that is not in the record.",
                })
                continue
            if source.record_status == "no_record_found":
                flags.append({
                    "claim_id": claim.id,
                    "claim_evidence_id": link.id,
                    "kind": "not_findable",
                    "detail": f"Cited source '{source.title}' is marked not findable. cited source: no record found",
                })
        from app.services.claim_confidence import assess_claim

        assessment = assess_claim(db, claim.id)
        if assessment.get("label") == "Refuted":
            flags.append({
                "claim_id": claim.id,
                "claim_evidence_id": None,
                "kind": "refuted",
                "detail": "Recorded counterevidence on this claim is stronger. This is not a judgment of the speaker.",
            })
    return flags
