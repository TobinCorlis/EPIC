import re
from dataclasses import dataclass, asdict

from app.services.moderation import evaluate_topic_alignment

FACT_MARKERS = re.compile(r"\b(\d+(?:\.\d+)?%?|according to|study|report|data|rate|increased|decreased|million|billion|research shows)\b", re.I)
URL_RE = re.compile(r"https?://[^\s)\]]+", re.I)

@dataclass(frozen=True)
class TurnAnalysis:
    on_topic: bool
    pivot_detected: bool
    citation_required: bool
    citation_present: bool
    rebuttal_target_required: bool
    approved: bool
    reasons: list[str]
    needs_review: bool = False

    def to_dict(self):
        return asdict(self)


def analyze_turn(fixed_question: str, body: str, rebuttal_target_turn_id: int | None = None) -> TurnAnalysis:
    topic = evaluate_topic_alignment(fixed_question, body)
    citation_required = bool(FACT_MARKERS.search(body))
    citation_present = bool(URL_RE.search(body))
    rebuttal_language = bool(re.search(r"\b(rebut|respond|response|opponent|previous claim|that claim)\b", body, re.I))
    target_required = rebuttal_language and rebuttal_target_turn_id is None and len(body.split()) >= 5
    reasons: list[str] = []
    if topic.needs_review:
        reasons.append(topic.note or "Flagged for review.")
    if citation_required and not citation_present:
        reasons.append("A factual assertion appears to require a citation.")
    if target_required:
        reasons.append("A rebuttal must identify the turn it answers.")
    approved = (not topic.needs_review) and not target_required and (not citation_required or citation_present)
    return TurnAnalysis(
        on_topic=True,
        pivot_detected=False,
        citation_required=citation_required,
        citation_present=citation_present,
        rebuttal_target_required=target_required,
        approved=approved,
        reasons=reasons,
        needs_review=topic.needs_review,
    )
