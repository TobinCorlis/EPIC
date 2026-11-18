from types import SimpleNamespace

from app.models.evidence import EvidenceStance, SourceType
from app.services.evidence_scoring import score_source, summarize_evidence


def make_link(
    link_id: int,
    stance: EvidenceStance,
    source_type: SourceType,
    *,
    reviewed: bool = False,
    publisher: str | None = None,
    url: str | None = None,
    claim_supported: str = "The cited passage states this claim.",
):
    source = SimpleNamespace(
        id=link_id,
        source_type=source_type,
        source_type_reviewed=reviewed,
        publisher=publisher,
        url=url,
        document_reference=None,
    )
    citation = SimpleNamespace(source=source)
    return SimpleNamespace(
        id=link_id,
        stance=stance,
        relevance_score=0.9,
        citation=citation,
        claim_supported=claim_supported,
    )


def test_declared_type_and_bylines_do_not_create_a_quality_score():
    primary_score, primary_reason = score_source(SourceType.primary_law, "Legislature", "Clerk")
    blog_score, blog_reason = score_source(SourceType.user_generated, None, None)
    assert primary_score == 0.0
    assert blog_score == 0.0
    assert "unverified" in primary_reason
    assert "does not add points" in primary_reason
    assert "does not add points" in blog_reason


def test_summary_ranks_by_tier_and_does_not_sum_volume():
    government = make_link(
        1,
        EvidenceStance.supports,
        SourceType.government_record,
        reviewed=True,
        publisher="Example Agency",
        url="https://example.gov/record",
    )
    blogs = [
        make_link(
            index,
            EvidenceStance.supports,
            SourceType.user_generated,
            reviewed=True,
            publisher=f"Blog {index}",
            url=f"https://blog{index}.example/post",
        )
        for index in range(2, 8)
    ]
    unreviewed_claim = make_link(
        8,
        EvidenceStance.supports,
        SourceType.primary_law,
        reviewed=False,
        publisher="Someone",
        url="https://example.com/unreviewed",
    )
    result = summarize_evidence([unreviewed_claim, *blogs, government])
    assert not hasattr(result, "net_evidence_score")
    assert result.items[0].claim_evidence_id == 1
    assert result.items[0].effective_tier == "government_record"
    assert result.strongest_effective_tier == "government_record"
    assert result.items[-1].effective_tier == "unknown"
    assert result.items[-1].declared_source_type == "primary_law"
    assert result.items[-1].source_type_reviewed is False
    assert result.independent_source_count == 8
    assert result.citation_count == 8


def test_same_publisher_counts_as_one_independent_source():
    links = [
        make_link(1, EvidenceStance.supports, SourceType.official_data, reviewed=True, publisher="Example Agency"),
        make_link(2, EvidenceStance.contradicts, SourceType.official_data, reviewed=True, publisher="Example Agency"),
    ]
    result = summarize_evidence(links)
    assert result.independent_source_count == 1
    assert {item.stance for item in result.items} == {"supports", "contradicts"}
