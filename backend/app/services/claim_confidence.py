"""Auditable claim confidence. This is not a verification and not a truth probability.

EPIC rules used here:
- Primary and official records outrank weaker tiers. Unreviewed self-declared
  types stay unknown and are not given that tier's weight.
- A source's track record is counted only from corrections, retractions,
  upheld challenges, and denied challenges actually stored in EPIC.
- No track record is unknown, not zero. Zero would say the source was disproven.
- Independent corroboration saturates. Extra items of the same low tier do not
  outweigh one stronger record.
- Counterevidence counts only when it is recorded and has not itself been
  refuted. Refuted contrary evidence is reported and then excluded.
- Automated checking of external sources is not implemented. This function
  never fetches a source and never sets verified or archived.

confidence = tier_factor * track_factor * corroboration_factor * counter_factor
when a supporting link exists. track_factor is omitted from the product when
the source has no record. The score is null when nothing supports the claim.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.core.clock import utcnow
from app.models.argument import EvidenceChallenge
from app.models.evidence import Citation, ClaimEvidence, EvidenceStance, Source
from app.models.knowledge import KnowledgeClaim, KnowledgeStatus
from app.models.verification import VerificationEvent, VerificationSubject
from app.services.evidence_scoring import TIER_RANK, effective_source_type, independence_key

AUTOMATED_SOURCE_CHECK = "not_implemented"
AUTOMATED_SOURCE_CHECK_DETAIL = (
    "Automated source checking is not implemented. No external source was fetched or compared."
)


@dataclass
class SourceRecord:
    source_id: int
    corrected: int
    retracted: int
    found_false: int
    confirmed: int

    @property
    def adverse(self) -> int:
        return self.corrected + self.retracted + self.found_false

    @property
    def track_factor(self) -> float | None:
        total = self.confirmed + self.adverse
        if total == 0:
            return None
        return self.confirmed / total


def source_record(db: Session, source_id: int) -> SourceRecord:
    link_ids = [
        row[0]
        for row in (
            db.query(ClaimEvidence.id)
            .join(Citation, Citation.id == ClaimEvidence.citation_id)
            .filter(Citation.source_id == source_id)
            .all()
        )
    ]
    claim_ids = [
        row[0]
        for row in (
            db.query(ClaimEvidence.claim_id)
            .join(Citation, Citation.id == ClaimEvidence.citation_id)
            .filter(Citation.source_id == source_id)
            .all()
        )
    ]
    found_false = 0
    confirmed = 0
    if link_ids:
        challenges = db.query(EvidenceChallenge).filter(EvidenceChallenge.claim_evidence_id.in_(link_ids)).all()
        found_false = sum(1 for challenge in challenges if challenge.status.value == "upheld")
        confirmed = sum(1 for challenge in challenges if challenge.status.value == "denied")
    corrected = 0
    retracted = 0
    if claim_ids:
        from app.models.correction import ClaimCorrection

        corrections = db.query(ClaimCorrection).filter(ClaimCorrection.claim_id.in_(claim_ids)).all()
        corrected = sum(1 for item in corrections if item.kind == "text" and item.original_body != item.corrected_body)
        knowledge = db.query(KnowledgeClaim).filter(KnowledgeClaim.originating_claim_id.in_(claim_ids)).all()
        retracted = sum(1 for item in knowledge if item.status in {KnowledgeStatus.archived, KnowledgeStatus.retired})
        still_verified = [item.id for item in knowledge if item.status == KnowledgeStatus.verified]
        if still_verified:
            confirmed += (
                db.query(VerificationEvent)
                .filter(
                    VerificationEvent.subject_type == VerificationSubject.knowledge_claim,
                    VerificationEvent.subject_id.in_(still_verified),
                    VerificationEvent.result_status == "verified",
                    VerificationEvent.mistake_reason.is_(None),
                )
                .count()
            )
    return SourceRecord(source_id, corrected, retracted, found_false, confirmed)


def _factor(name: str, value: float | None, detail: str) -> dict:
    return {"name": name, "value": value, "detail": detail}


def assess_claim(db: Session, claim_id: int) -> dict:
    links = (
        db.query(ClaimEvidence)
        .options(joinedload(ClaimEvidence.citation).joinedload(Citation.source), joinedload(ClaimEvidence.challenges))
        .filter(ClaimEvidence.claim_id == claim_id)
        .all()
    )
    supporting = [link for link in links if link.stance == EvidenceStance.supports]
    contradicting = [link for link in links if link.stance == EvidenceStance.contradicts]
    if not supporting:
        breakdown = {
            "confidence_score": None,
            "automated_source_check": AUTOMATED_SOURCE_CHECK,
            "automated_source_check_detail": AUTOMATED_SOURCE_CHECK_DETAIL,
            "factors": [
                _factor("tier", None, "No supporting evidence is recorded, so tier weight is unknown."),
                _factor("track_record", None, "No supporting source is recorded."),
                _factor("independent_corroboration", 0.0, "0 independent supporting sources."),
                _factor("counterevidence", None, "Not applied without supporting evidence."),
            ],
        }
        _store(db, claim_id, breakdown)
        return breakdown

    def tier_of(link: ClaimEvidence) -> int:
        source = link.citation.source
        effective = effective_source_type(source.source_type, source.source_type_reviewed)
        return TIER_RANK[effective]

    best = max(supporting, key=tier_of)
    best_source = best.citation.source
    best_tier = tier_of(best)
    tier_factor = best_tier / 8
    tier_detail = (
        f"Strongest supporting source is '{best_source.title}' "
        f"with effective tier rank {best_tier} of 8. "
        "Unreviewed declared types are unknown and are not given their declared rank. "
        "Tiers are not added across items."
    )
    record = source_record(db, best_source.id)
    if record.track_factor is None:
        track_detail = (
            f"Source {best_source.id} has no recorded corrections, retractions, upheld challenges, "
            "or confirmations. That is unknown, not a score of zero."
        )
    else:
        track_detail = (
            f"Source {best_source.id}: confirmed {record.confirmed}, corrected {record.corrected}, "
            f"retracted {record.retracted}, found false {record.found_false}. "
            "The factor is confirmed / (confirmed + adverse) for this source only."
        )
    independent = {independence_key(link.citation.source) for link in supporting}
    corroboration = min(len(independent), 3) / 3
    corr_detail = (
        f"{len(independent)} independent supporting source(s). "
        "The factor saturates at 3 and does not grow with more items of the same tier."
    )
    unrefuted = []
    refuted = []
    for link in contradicting:
        upheld = any(challenge.status.value == "upheld" for challenge in link.challenges)
        if upheld:
            refuted.append(link)
        else:
            unrefuted.append(link)
    unrefuted_keys = {independence_key(link.citation.source) for link in unrefuted}
    counter_factor = 1 / (1 + len(unrefuted_keys))
    counter_detail = (
        f"{len(contradicting)} contradicting link(s) recorded; "
        f"{len(refuted)} refuted by an upheld challenge and excluded; "
        f"{len(unrefuted_keys)} independent unrefuted contrary source(s) remain. "
        "Nothing outside EPIC is assumed."
    )
    score = tier_factor * corroboration * counter_factor
    if record.track_factor is not None:
        score *= record.track_factor
    score = round(score, 3)
    breakdown = {
        "confidence_score": score,
        "automated_source_check": AUTOMATED_SOURCE_CHECK,
        "automated_source_check_detail": AUTOMATED_SOURCE_CHECK_DETAIL,
        "factors": [
            _factor("tier", tier_factor, tier_detail),
            _factor("track_record", record.track_factor, track_detail),
            _factor("independent_corroboration", corroboration, corr_detail),
            _factor("counterevidence", counter_factor, counter_detail),
        ],
    }
    _store(db, claim_id, breakdown)
    for knowledge in db.query(KnowledgeClaim).filter(KnowledgeClaim.originating_claim_id == claim_id):
        if knowledge.status not in {KnowledgeStatus.verified, KnowledgeStatus.archived}:
            knowledge.confidence_score = score
    return breakdown


def _store(db: Session, claim_id: int, breakdown: dict) -> None:
    from app.models.confidence import ClaimConfidenceAssessment

    row = db.query(ClaimConfidenceAssessment).filter(ClaimConfidenceAssessment.claim_id == claim_id).one_or_none()
    if row is None:
        row = ClaimConfidenceAssessment(claim_id=claim_id)
        db.add(row)
    row.confidence_score = breakdown["confidence_score"]
    row.breakdown_json = json.dumps(breakdown)
    row.automated_source_check = AUTOMATED_SOURCE_CHECK
    row.computed_at = utcnow()
