from types import SimpleNamespace

from app.models.evidence import EvidenceStance, SourceType
from app.services.evidence_scoring import score_source, summarize_evidence


def make_link(stance: EvidenceStance, quality: float, relevance: float):
    source = SimpleNamespace(quality_score=quality)
    citation = SimpleNamespace(source=source)
    return SimpleNamespace(stance=stance, relevance_score=relevance, citation=citation)


def test_primary_source_scores_higher_than_unknown_source():
    primary_score, _ = score_source(SourceType.primary_law, "Legislature", "Clerk")
    unknown_score, _ = score_source(SourceType.unknown, None, None)
    assert primary_score > unknown_score
    assert primary_score == 1.0


def test_evidence_summary_weights_quality_and_relevance():
    links = [
        make_link(EvidenceStance.supports, quality=0.9, relevance=0.8),
        make_link(EvidenceStance.contradicts, quality=0.5, relevance=0.4),
        make_link(EvidenceStance.contextualizes, quality=0.7, relevance=0.5),
    ]
    result = summarize_evidence(links)
    assert result.supports_score == 0.72
    assert result.contradicts_score == 0.2
    assert result.contextual_score == 0.35
    assert result.net_evidence_score == 0.52
    assert result.citation_count == 3
