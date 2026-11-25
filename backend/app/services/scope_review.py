"""Rule-based scope checks. These flags mean needs-review, not rejection.

Detection uses only scope text the user entered on the source, the evidence
link, the claim, and the debate question, plus a few wording patterns
(all/some, causation language, national wording). It does not read an
external study. An outlier is flagged only when EPIC already has a recorded
contradicting link on the same claim.
"""
import re

from sqlalchemy.orm import Session, joinedload

from app.models.claim import Claim
from app.models.debate import Debate
from app.models.evidence import Citation, ClaimEvidence, EvidenceStance
from app.models.scope import ScopeReviewFlag

RULE_NOTE = (
    "Needs review. This is a rule-based comparison of user-entered scope fields "
    "and wording, not a finding that the evidence is false or off-topic."
)
_CAUSAL = re.compile(r"\b(causes?|caused|causation)\b", re.I)
_NATIONAL = re.compile(r"\b(national|nationwide|the country|countrywide)\b", re.I)
_LOCAL = re.compile(r"\b(city|county|state|province|town)\b", re.I)
_ALL = re.compile(r"\ball\b", re.I)
_SOME = re.compile(r"\bsome\b", re.I)


def _norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _measured(link: ClaimEvidence, name: str) -> str | None:
    link_value = getattr(link, f"scope_{name}", None)
    source_value = getattr(link.citation.source, f"scope_{name}", None)
    return link_value or source_value


def review_claim_scope(db: Session, claim: Claim) -> list[ScopeReviewFlag]:
    debate = db.get(Debate, claim.debate_id)
    links = (
        db.query(ClaimEvidence)
        .options(joinedload(ClaimEvidence.citation).joinedload(Citation.source))
        .filter(ClaimEvidence.claim_id == claim.id)
        .all()
    )
    flags: list[ScopeReviewFlag] = []

    def add(kind: str, dimension: str, source_text: str, claim_text: str, link_id: int | None) -> None:
        flags.append(ScopeReviewFlag(
            claim_id=claim.id,
            claim_evidence_id=link_id,
            kind=kind,
            dimension=dimension,
            source_text=source_text,
            claim_text=claim_text,
            note=RULE_NOTE,
        ))

    for name in ("population", "timeframe", "geography", "metric"):
        claim_value = _norm(getattr(claim, f"scope_{name}", None))
        question_value = _norm(getattr(debate, f"question_{name}", None) if debate else None)
        if claim_value and question_value and claim_value != question_value:
            add("question_drift", name, question_value, claim_value, None)
        for link in links:
            measured = _norm(_measured(link, name))
            if claim_value and measured and claim_value != measured:
                add("scope_mismatch", name, _measured(link, name) or "", getattr(claim, f"scope_{name}") or "", link.id)

    for link in links:
        measured_population = _measured(link, "population") or ""
        study_type = (_measured(link, "study_type") or "").lower()
        geography = _measured(link, "geography") or ""
        excerpt = link.citation.excerpt or ""
        if _ALL.search(claim.body) and (_SOME.search(measured_population) or _SOME.search(excerpt)):
            add("overgeneralization", "breadth", measured_population or excerpt, claim.body, link.id)
        if _CAUSAL.search(claim.body) and study_type in {"correlation", "observational", "cross-sectional"}:
            add("overgeneralization", "causation", study_type, claim.body, link.id)
        if _NATIONAL.search(claim.body) and _LOCAL.search(geography):
            add("overgeneralization", "geography", geography, claim.body, link.id)

    from app.models.factcheck import SourceCheck

    suggestions = (
        db.query(SourceCheck)
        .filter(SourceCheck.claim_id == claim.id, SourceCheck.checker_name == "related_work")
        .all()
    )
    seen_suggestions = set()
    for check in suggestions:
        if not (check.detail or "").startswith("Systematic review"):
            continue
        key = check.evidence_url or check.response_id or str(check.id)
        if key in seen_suggestions:
            continue
        seen_suggestions.add(key)
        flags.append(ScopeReviewFlag(
            claim_id=claim.id,
            claim_evidence_id=None,
            kind="consensus_suggestion",
            dimension="literature",
            source_text=check.evidence_url or check.response_id or "",
            claim_text=claim.body,
            note=(
                "Suggestion only. An automated search returned a systematic review or meta-analysis. "
                "It is not linked evidence and does not change the score."
            ),
        ))

    supporting = [link for link in links if link.stance == EvidenceStance.supports]
    contradicting = [link for link in links if link.stance == EvidenceStance.contradicts]
    if len(supporting) == 1 and contradicting:
        add(
            "outlier",
            "representativeness",
            supporting[0].citation.source.title,
            claim.body,
            supporting[0].id,
        )

    db.query(ScopeReviewFlag).filter(ScopeReviewFlag.claim_id == claim.id).delete()
    for flag in flags:
        db.add(flag)
    if flags:
        claim.needs_review = True
    return flags
