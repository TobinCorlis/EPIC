"""Auditable claim confidence. This is not a verification and not a truth probability.

Credibility is judged only on checkable evidence for this claim: whether the
data or method was reviewed, whether the cited study or test was found and
done, the source's record of corrections and false information, and
independent corroboration. Publisher, author, and group names are not score
weights. EPIC does not censor. A correct sub-claim keeps its own support when
a different conclusion from the same source is Refuted. Nothing is Refuted
without recorded counterevidence on that claim.

Scoring rules, applied in this order:
0. A question marked not factually answerable gets no score and no
   Supported or Refuted label.
1. No supporting evidence, or a cited source with no findable record, scores 0
   and is labeled Unsupported. The missing citation is recorded as
   'cited source: no record found'. A source counts as findable when a person
   records that the record was found, or when they review its tier, unless an
   automated lookup has recorded that it is not findable. A lookup that fails
   is check_failed: it is not a verification and it is not a missing record.
2. A claim contradicted by stronger, independent, reviewed evidence scores 0
   and is labeled Refuted. The contradicting sources are listed. Weaker or
   non-independent contradiction does not force that label.
3. Supported and Verified require at least one supporting source whose tier
   a person has reviewed and which was not recorded as missing. Callers
   downgrade or block those statuses otherwise and flag the claim for review.
4. 'Unknown – not yet rated' is only for evidence a person has found but whose
   tier is not reviewed yet. It is never used for a missing citation.
5. When those gates pass, the score is
   tier_factor * track_factor * corroboration_factor * counter_factor.
   A missing track record stays unknown and is left out of the product.
   It is not a zero. Status changes come from recorded human review.

The scale is 0–1. Factor values are rounded to two decimals.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.core.clock import utcnow
from app.models.argument import EvidenceChallenge
from app.models.claim import Claim
from app.models.evidence import Citation, ClaimEvidence, EvidenceStance, Source
from app.models.knowledge import KnowledgeClaim, KnowledgeStatus
from app.models.verification import VerificationEvent, VerificationSubject
from app.services.evidence_scoring import TIER_RANK, effective_source_type, independence_key

AUTOMATED_SOURCE_CHECK = "not_checked"
AUTOMATED_SOURCE_CHECK_DETAIL = (
    "No automated source check has been recorded. That is not a verification."
)
LABEL_UNSUPPORTED = "Unsupported"
LABEL_REFUTED = "Refuted"
LABEL_UNRATED = "Unknown – not yet rated"
LABEL_RATED = "Rated"
LABEL_SUPPORTED = "Supported"
LABEL_WEAK = "Weakly supported"
FACTCHECK_REASON_CODES = {
    "no_record",
    "quote_not_found",
    "text_not_accessible",
    "low_confidence",
    "check_failed",
    "metadata_mismatch",
    "retraction",
    "refuted",
}
NO_RECORD = "cited source: no record found"
SCORE_SCALE = "0–1"
SUPPORT_RULE = "Supported or verified requires recorded supporting evidence with a reviewed tier."


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
        if self.retracted:
            return 0.0
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
    from app.models.library import UpstreamInvalidation

    retracted += (
        db.query(UpstreamInvalidation)
        .filter(
            UpstreamInvalidation.subject_type == "source",
            UpstreamInvalidation.subject_id == source_id,
            UpstreamInvalidation.reversed_reason.is_(None),
        )
        .count()
    )
    return SourceRecord(source_id, corrected, retracted, found_false, confirmed)


def _factor(name: str, value: float | None, detail: str) -> dict:
    rounded = None if value is None else round(float(value), 2)
    return {"name": name, "value": rounded, "detail": detail}


def _record_status(source) -> str:
    return getattr(source, "record_status", None) or "not_checked"


def source_has_reviewed_support(source, findability: str | None = None) -> bool:
    """A person reviewed the tier, and the record was not found to be missing."""
    if findability == "not_findable":
        return False
    return bool(source.source_type_reviewed) and _record_status(source) != "no_record_found"


def source_is_unrated(source, findability: str | None = None, confirmed: bool = False) -> bool:
    """The record was found, and its tier has not been reviewed."""
    if findability == "not_findable":
        return False
    if confirmed and not source.source_type_reviewed:
        return True
    return _record_status(source) == "found" and not source.source_type_reviewed


def source_has_no_record(source, findability: str | None = None, confirmed: bool = False) -> bool:
    if findability == "not_findable":
        return True
    if confirmed:
        return False
    status = _record_status(source)
    if status == "no_record_found":
        return True
    if status == "found" or source.source_type_reviewed:
        return False
    return True


def _tier(source, confirmed: bool = False) -> int:
    if confirmed:
        return TIER_RANK[source.source_type]
    effective = effective_source_type(source.source_type, source.source_type_reviewed)
    return TIER_RANK[effective]


def support_qualifies(db: Session, claim_ids: list[int]) -> bool:
    if not claim_ids:
        return False
    links = (
        db.query(ClaimEvidence)
        .options(joinedload(ClaimEvidence.citation).joinedload(Citation.source))
        .filter(ClaimEvidence.claim_id.in_(claim_ids), ClaimEvidence.stance == EvidenceStance.supports)
        .all()
    )
    from app.services.factcheck.status import findability_for_source

    return any(
        link.citation
        and link.citation.source
        and source_has_reviewed_support(
            link.citation.source,
            findability_for_source(db, link.citation.source.id),
        )
        for link in links
    )


def replace_factcheck_reasons(claim, reasons: list[str]) -> None:
    """Replace fact-check reasons and keep reasons set by other checks."""
    raw = getattr(claim, "needs_review_reasons", None) or "[]"
    try:
        current = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except json.JSONDecodeError:
        current = []
    if not isinstance(current, list):
        current = []
    kept = [item for item in current if item not in FACTCHECK_REASON_CODES]
    merged = kept + [item for item in reasons if item not in kept]
    claim.needs_review_reasons = json.dumps(merged)
    claim.needs_review = bool(merged)


def merge_review_reason(claim, code: str, present: bool) -> None:
    raw = getattr(claim, "needs_review_reasons", None) or "[]"
    try:
        current = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except json.JSONDecodeError:
        current = []
    if not isinstance(current, list):
        current = []
    current = [item for item in current if item != code]
    if present:
        current.append(code)
    claim.needs_review_reasons = json.dumps(current)
    claim.needs_review = bool(current)


def _apply_support_label(breakdown: dict, claim, *, attribution_verified: bool, independent_count: int) -> None:
    """Supported requires the score threshold and the evidence gate. A low score never carries it."""
    from app.core.config import settings

    score = breakdown.get("confidence_score")
    label = breakdown.get("label")
    breakdown["support_threshold"] = settings.support_score_threshold
    breakdown["attribution_verified"] = attribution_verified
    breakdown["claim_role"] = getattr(claim, "claim_role", None) or "substantive"
    breakdown["attribution_note"] = (
        "Attribution verified: the cited source contains this text. That is not a finding that the claim is true."
        if attribution_verified
        else "Attribution is not verified. A quote match is not assumed."
    )
    if label in {LABEL_UNSUPPORTED, LABEL_REFUTED} or score == 0:
        return
    if score is None:
        return
    role = breakdown["claim_role"]
    if role == "attribution":
        eligible = attribution_verified
    else:
        eligible = independent_count >= 2
    if eligible and score >= settings.support_score_threshold:
        breakdown["label"] = LABEL_SUPPORTED
    elif score > 0:
        breakdown["label"] = LABEL_WEAK


def _assessment(
    score,
    label: str,
    factors: list[dict],
    note: str | None = None,
    contradicting: list[dict] | None = None,
    automated: str = AUTOMATED_SOURCE_CHECK,
    automated_detail: str = AUTOMATED_SOURCE_CHECK_DETAIL,
) -> dict:
    return {
        "confidence_score": score,
        "label": label,
        "scale": SCORE_SCALE,
        "cited_source_note": note,
        "contradicting_sources": contradicting or [],
        "automated_source_check": automated,
        "automated_source_check_detail": automated_detail,
        "factors": factors,
    }


def _source_brief(link: ClaimEvidence) -> dict:
    source = link.citation.source
    return {"id": source.id, "title": source.title, "tier_rank": _tier(source)}


def assess_claim(db: Session, claim_id: int) -> dict:
    claim = db.get(Claim, claim_id)
    if claim is not None and claim.answerability == "not_factually_answerable":
        breakdown = _assessment(None, "", [])
        breakdown["label"] = None
        breakdown["not_factually_answerable"] = True
        breakdown["answerability_reason"] = claim.answerability_reason
        breakdown["scale"] = None
        _store(db, claim_id, breakdown)
        for knowledge in db.query(KnowledgeClaim).filter(KnowledgeClaim.originating_claim_id == claim_id):
            if knowledge.status not in {KnowledgeStatus.verified, KnowledgeStatus.archived}:
                knowledge.confidence_score = None
        return breakdown

    links = (
        db.query(ClaimEvidence)
        .options(joinedload(ClaimEvidence.citation).joinedload(Citation.source), joinedload(ClaimEvidence.challenges))
        .filter(ClaimEvidence.claim_id == claim_id)
        .all()
    )
    from app.services.factcheck.status import (
        automated_record_found,
        describe_sources,
        findability_for_source,
        has_retraction,
        latest_quote_by_citation,
        llm_supports_claim,
        provenance_line,
        review_signal,
    )

    supporting = [link for link in links if link.stance == EvidenceStance.supports and link.citation and link.citation.source]
    contradicting = [link for link in links if link.stance == EvidenceStance.contradicts and link.citation and link.citation.source]
    findability = {
        link.citation.source.id: findability_for_source(db, link.citation.source.id)
        for link in supporting + contradicting
    }
    confirmed = {source_id: automated_record_found(db, source_id) for source_id in findability}
    retracted = {source_id for source_id in findability if has_retraction(db, source_id)}
    quote_by = latest_quote_by_citation(db, [link.citation_id for link in supporting])
    llm_ok = llm_supports_claim(db, claim_id)
    weighed = []
    quote_blocked = []
    for link in supporting:
        source = link.citation.source
        source_id = source.id
        quote = quote_by.get(link.citation_id)
        if source_id in retracted or findability.get(source_id) == "not_findable":
            continue
        if quote == "quote_not_found":
            quote_blocked.append(link)
            continue
        quote_ok = quote == "quote_found" or (llm_ok and confirmed.get(source_id))
        reviewed = source_has_reviewed_support(source, findability.get(source_id))
        role = (claim.claim_role if claim is not None else None) or "substantive"
        if role == "attribution":
            if confirmed.get(source_id) and quote_ok:
                weighed.append(link)
        elif reviewed:
            weighed.append(link)
    unrated = [
        link for link in supporting
        if source_is_unrated(
            link.citation.source,
            findability.get(link.citation.source.id),
            confirmed.get(link.citation.source.id, False),
        )
        and link not in weighed
        and link not in quote_blocked
    ]
    missing = [
        link for link in supporting
        if source_has_no_record(
            link.citation.source,
            findability.get(link.citation.source.id),
            confirmed.get(link.citation.source.id, False),
        )
    ]
    missing_note = NO_RECORD if missing else None

    def stronger_contradictions() -> list[ClaimEvidence]:
        support_keys = {independence_key(link.citation.source) for link in supporting}
        best = max((_tier(link.citation.source) for link in weighed), default=None)
        found = []
        for link in contradicting:
            source = link.citation.source
            if not source_has_reviewed_support(source, findability.get(source.id)):
                continue
            if any(challenge.status.value == "upheld" for challenge in link.challenges):
                continue
            if independence_key(source) in support_keys:
                continue
            if best is None or _tier(source) > best:
                found.append(link)
        return found

    stronger = stronger_contradictions()
    if not supporting:
        breakdown = _assessment(
            0,
            LABEL_UNSUPPORTED,
            [
                _factor("tier", None, "No supporting evidence is recorded."),
                _factor("track_record", None, "No supporting source is recorded."),
                _factor("independent_corroboration", 0.0, "0 independent supporting sources."),
                _factor("counterevidence", None, "Not applied without supporting evidence."),
            ],
        )
    elif stronger:
        titles = ", ".join(f"'{link.citation.source.title}'" for link in stronger)
        breakdown = _assessment(
            0,
            LABEL_REFUTED,
            [
                _factor("tier", 0.0, f"Stronger independent contradicting evidence is recorded: {titles}."),
                _factor("track_record", None, "Not applied. The claim is refuted by stronger recorded evidence."),
                _factor("independent_corroboration", 0.0, "Supporting corroboration does not outrank the contradicting sources."),
                _factor("counterevidence", 0.0, f"{len(stronger)} stronger independent contradicting source(s)."),
            ],
            note=missing_note,
            contradicting=[_source_brief(link) for link in stronger],
        )
    elif weighed:
        breakdown = _rated_breakdown(
            db,
            weighed,
            contradicting,
            missing_note,
            label=LABEL_RATED,
            confirmed=confirmed,
            attribution=(claim.claim_role if claim is not None else None) == "attribution",
        )
    elif quote_blocked:
        breakdown = _assessment(
            None,
            LABEL_UNRATED,
            [
                _factor("tier", None, "The cited record was found, but the quoted text was not in the accessible text. Attribution is not verified. This is not a finding that the claim is false."),
                _factor("track_record", None, "Not applied until the quoted text is found."),
                _factor("independent_corroboration", None, "A missing quote does not corroborate the claim."),
                _factor("counterevidence", None, "Not applied."),
            ],
        )
    elif unrated and not missing:
        titles = ", ".join(f"'{link.citation.source.title}'" for link in unrated)
        breakdown = _assessment(
            None,
            LABEL_UNRATED,
            [
                _factor("tier", None, f"Record found for {titles}, and the tier has not been reviewed. This is not a score of zero."),
                _factor("track_record", None, "Not weighed until the tier is reviewed."),
                _factor("independent_corroboration", None, "Not weighed until the tier is reviewed."),
                _factor("counterevidence", None, "Not weighed until the supporting tier is reviewed."),
            ],
        )
    else:
        titles = ", ".join(f"'{link.citation.source.title}'" for link in missing) or "the cited source"
        breakdown = _assessment(
            0,
            LABEL_UNSUPPORTED,
            [
                _factor("tier", 0.0, f"{NO_RECORD}: {titles}."),
                _factor("track_record", None, "No findable supporting record is available to score."),
                _factor("independent_corroboration", 0.0, "A missing citation does not corroborate the claim."),
                _factor("counterevidence", None, "Not applied. The supporting citation has no findable record."),
            ],
            note=NO_RECORD,
        )
    automated, automated_detail = describe_sources(db, [link.citation.source.id for link in supporting])
    breakdown["automated_source_check"] = automated
    breakdown["automated_source_check_detail"] = automated_detail
    line = next((provenance_line(db, source_id) for source_id in findability if provenance_line(db, source_id)), None)
    if line:
        for factor in breakdown["factors"]:
            if line not in factor["detail"]:
                factor["detail"] = f"{factor['detail']} {line}"
    attribution_verified = any(
        (quote_by.get(link.citation_id) == "quote_found" or (llm_ok and confirmed.get(link.citation.source.id)))
        and link.citation.source.id not in retracted
        and findability.get(link.citation.source.id) != "not_findable"
        for link in supporting
    )
    independent_count = len({independence_key(link.citation.source) for link in weighed})
    claim = db.get(Claim, claim_id)
    if claim is not None:
        _apply_support_label(
            breakdown,
            claim,
            attribution_verified=attribution_verified,
            independent_count=independent_count,
        )
        reasons = []
        if breakdown.get("cited_source_note") == NO_RECORD or any(status == "not_findable" for status in findability.values()):
            reasons.append("no_record")
        if any(quote_by.get(link.citation_id) == "quote_not_found" for link in supporting):
            reasons.append("quote_not_found")
        if any(quote_by.get(link.citation_id) == "text_not_accessible" for link in supporting):
            reasons.append("text_not_accessible")
        if any(status == "low_confidence" for status in findability.values()):
            reasons.append("low_confidence")
        if any(status == "check_failed" for status in findability.values()):
            reasons.append("check_failed")
        if any(review_signal(db, source_id) for source_id in findability):
            from app.services.factcheck.status import source_rows

            for source_id in findability:
                latest = {row.checker_name: row for row in source_rows(db, source_id)}
                if latest.get("metadata") is not None and latest["metadata"].result == "mismatch":
                    reasons.append("metadata_mismatch")
                if latest.get("retraction") is not None and latest["retraction"].result == "retracted":
                    reasons.append("retraction")
        if breakdown.get("label") == LABEL_REFUTED:
            reasons.append("refuted")
        replace_factcheck_reasons(claim, list(dict.fromkeys(reasons)))
    else:
        _apply_support_label(
            breakdown,
            type("ClaimRole", (), {"claim_role": "substantive"})(),
            attribution_verified=attribution_verified,
            independent_count=independent_count,
        )
    _store(db, claim_id, breakdown)
    _apply_to_knowledge(db, claim_id, breakdown)
    return breakdown


def _rated_breakdown(
    db: Session,
    weighed: list[ClaimEvidence],
    contradicting: list[ClaimEvidence],
    missing_note: str | None,
    quote_missing: bool = False,
    label: str = LABEL_RATED,
    confirmed: dict | None = None,
    attribution: bool = False,
) -> dict:
    confirmed = confirmed or {}
    best = max(weighed, key=lambda link: _tier(link.citation.source, confirmed.get(link.citation.source.id, False)))
    best_source = best.citation.source
    best_confirmed = bool(confirmed.get(best_source.id))
    best_tier = _tier(best_source, best_confirmed)
    tier_factor = best_tier / 8
    if best_confirmed and not best_source.source_type_reviewed:
        tier_detail = (
            f"Strongest supporting source is '{best_source.title}' "
            f"with declared tier rank {best_tier} of 8 after an automated check matched the identifier and metadata. "
            "Tiers are not added across items."
        )
    else:
        tier_detail = (
            f"Strongest supporting source is '{best_source.title}' "
            f"with reviewed tier rank {best_tier} of 8. "
            "Unreviewed declared types are not given their declared rank. Tiers are not added across items."
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
    independent = {independence_key(link.citation.source) for link in weighed}
    if attribution:
        corroboration = 1.0
        corroboration_detail = (
            f"{len(independent)} cited source(s). A single source containing the quoted text is not "
            "independent corroboration of a separate fact. The factor is 1 because this claim is only that the source says this."
        )
    else:
        corroboration = min(len(independent), 3) / 3
        corroboration_detail = f"{len(independent)} independent supporting source(s). The factor saturates at 3. One source is not enough to call a substantive claim Supported."
    unrefuted = []
    refuted_count = 0
    for link in contradicting:
        if any(challenge.status.value == "upheld" for challenge in link.challenges):
            refuted_count += 1
        else:
            unrefuted.append(link)
    unrefuted_keys = {independence_key(link.citation.source) for link in unrefuted}
    counter_factor = 1 / (1 + len(unrefuted_keys))
    score = tier_factor * corroboration * counter_factor
    if record.track_factor is not None:
        score *= record.track_factor
    if quote_missing:
        score *= 0.5
        tier_detail += (
            " A quoted passage was not found in the accessible text. Support is lowered "
            "and the claim is flagged for review. This is not a refutation."
        )
    return _assessment(
        round(score, 2),
        label,
        [
            _factor("tier", tier_factor, tier_detail),
            _factor("track_record", record.track_factor, track_detail),
            _factor("independent_corroboration", corroboration, corroboration_detail),
            _factor(
                "counterevidence",
                counter_factor,
                f"{len(contradicting)} contradicting link(s); {refuted_count} excluded after an upheld challenge; "
                f"{len(unrefuted_keys)} independent unrefuted contrary source(s) remain.",
            ),
        ],
        note=missing_note,
    )


def _apply_to_knowledge(db: Session, claim_id: int, breakdown: dict) -> None:
    from app.models.status_history import StatusHistory

    qualifies = support_qualifies(db, [claim_id])
    claim = db.get(Claim, claim_id)
    for knowledge in db.query(KnowledgeClaim).filter(KnowledgeClaim.originating_claim_id == claim_id):
        if knowledge.status == KnowledgeStatus.verified and not qualifies:
            previous = knowledge.status.value
            knowledge.status = KnowledgeStatus.unverified
            knowledge.confidence_score = 0
            db.add(StatusHistory(
                subject_type="knowledge_claim",
                subject_id=knowledge.id,
                previous_status=previous,
                new_status="unverified",
                note=f"Downgraded: {SUPPORT_RULE}",
            ))
            if claim is not None:
                claim.needs_review = True
            continue
        if knowledge.status not in {KnowledgeStatus.verified, KnowledgeStatus.archived}:
            knowledge.confidence_score = breakdown["confidence_score"]


def _store(db: Session, claim_id: int, breakdown: dict) -> None:
    from app.models.confidence import ClaimConfidenceAssessment

    row = db.query(ClaimConfidenceAssessment).filter(ClaimConfidenceAssessment.claim_id == claim_id).one_or_none()
    if row is None:
        row = ClaimConfidenceAssessment(claim_id=claim_id)
        db.add(row)
    row.confidence_score = breakdown["confidence_score"]
    row.breakdown_json = json.dumps(breakdown)
    row.automated_source_check = breakdown["automated_source_check"]
    row.computed_at = utcnow()
