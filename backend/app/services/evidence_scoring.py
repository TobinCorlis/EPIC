from dataclasses import dataclass

from app.models.evidence import ClaimEvidence, EvidenceStance, SourceType


SOURCE_BASE_SCORES: dict[SourceType, float] = {
    SourceType.primary_law: 0.98,
    SourceType.government_record: 0.92,
    SourceType.peer_reviewed: 0.90,
    SourceType.official_data: 0.90,
    SourceType.reputable_news: 0.72,
    SourceType.expert_analysis: 0.68,
    SourceType.advocacy: 0.48,
    SourceType.user_generated: 0.30,
    SourceType.unknown: 0.20,
}


def score_source(source_type: SourceType, publisher: str | None, author: str | None) -> tuple[float, str]:
    score = SOURCE_BASE_SCORES[source_type]
    reasons = [f"Base score for {source_type.value}: {score:.2f}."]

    if publisher:
        score += 0.03
        reasons.append("Identified publisher: +0.03.")
    if author:
        score += 0.02
        reasons.append("Identified author: +0.02.")

    final = round(min(score, 1.0), 2)
    reasons.append(f"Final provisional quality score: {final:.2f}.")
    return final, " ".join(reasons)


@dataclass(frozen=True)
class EvidenceSummary:
    supports_score: float
    contradicts_score: float
    contextual_score: float
    net_evidence_score: float
    citation_count: int


def summarize_evidence(links: list[ClaimEvidence]) -> EvidenceSummary:
    totals = {stance: 0.0 for stance in EvidenceStance}
    for link in links:
        source_quality = link.citation.source.quality_score
        weighted = source_quality * link.relevance_score
        totals[link.stance] += weighted

    supports = round(totals[EvidenceStance.supports], 3)
    contradicts = round(totals[EvidenceStance.contradicts], 3)
    contextual = round(totals[EvidenceStance.contextualizes], 3)
    return EvidenceSummary(
        supports_score=supports,
        contradicts_score=contradicts,
        contextual_score=contextual,
        net_evidence_score=round(supports - contradicts, 3),
        citation_count=len(links),
    )
