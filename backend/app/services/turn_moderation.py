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

    def to_dict(self):
        return asdict(self)


def analyze_turn(fixed_question: str, body: str, rebuttal_target_turn_id: int | None = None) -> TurnAnalysis:
    topic = evaluate_topic_alignment(fixed_question, body)
    pivot = bool(topic.note and "pivot" in topic.note.lower())
    # Very short turns often lack repeated question vocabulary; only explicit pivots
    # or substantial nonresponsive text are blocked automatically.
    if not topic.on_topic and not pivot and len(body.split()) < 18:
        from app.services.moderation import ModerationResult
        topic = ModerationResult(True)
    citation_required = bool(FACT_MARKERS.search(body))
    citation_present = bool(URL_RE.search(body))
    rebuttal_language = bool(re.search(r"\b(rebut|respond|response|opponent|previous claim|that claim)\b", body, re.I))
    target_required = rebuttal_language and rebuttal_target_turn_id is None and len(body.split()) >= 5
    reasons: list[str] = []
    if not topic.on_topic:
        reasons.append(topic.note or "Turn is not responsive to the fixed question.")
    if citation_required and not citation_present:
        reasons.append("A factual assertion appears to require a citation.")
    if target_required:
        reasons.append("A rebuttal must identify the turn it answers.")
    approved = topic.on_topic and not target_required and (not citation_required or citation_present)
    return TurnAnalysis(topic.on_topic, pivot, citation_required, citation_present, target_required, approved, reasons)
