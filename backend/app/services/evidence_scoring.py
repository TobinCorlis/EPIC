from dataclasses import dataclass
from urllib.parse import urlparse

from app.models.evidence import EvidenceStance, SourceType


# Higher ranks are stronger record types. Ranks are not points and are not added together.
TIER_RANK: dict[SourceType, int] = {
    SourceType.unknown: 0,
    SourceType.user_generated: 1,
    SourceType.advocacy: 2,
    SourceType.expert_analysis: 3,
    SourceType.reputable_news: 4,
    SourceType.peer_reviewed: 5,
    SourceType.official_data: 6,
    SourceType.government_record: 7,
    SourceType.primary_law: 8,
}


def effective_source_type(declared: SourceType, source_type_reviewed: bool) -> SourceType:
    """A self-declared type is not used until a reviewer has confirmed it."""
    if source_type_reviewed:
        return declared
    return SourceType.unknown


def score_source(
    source_type: SourceType,
    publisher: str | None,
    author: str | None,
    *,
    source_type_reviewed: bool = False,
) -> tuple[float, str]:
    """Return a non-additive quality placeholder and an explanation.

    Publisher and author text do not change the result. The numeric score
    stays 0 because EPIC ranks evidence by tier and independence instead of
    summing quality points.
    """
    del publisher, author
    declared = source_type.value
    if source_type_reviewed:
        rationale = (
            f"Declared source type '{declared}' has been reviewed. "
            f"Effective tier: {declared}. "
            "Publisher or author text does not add points, and items are not summed."
        )
    else:
        rationale = (
            f"Declared source type '{declared}' is unverified and is treated as unknown until reviewed. "
            "Publisher or author text does not add points, and items are not summed."
        )
    return 0.0, rationale


def independence_key(source) -> str:
    """Tell copies of one record apart. The name is not a credibility weight."""
    publisher = getattr(source, "publisher", None)
    if publisher and str(publisher).strip():
        return "publisher:" + str(publisher).strip().lower()
    url = getattr(source, "url", None)
    if url:
        host = urlparse(str(url)).netloc.lower()
        if host:
            return "host:" + host
    document = getattr(source, "document_reference", None)
    if document and str(document).strip():
        return "document:" + str(document).strip().lower()
    return f"source:{getattr(source, 'id', 'unknown')}"


@dataclass(frozen=True)
class EvidenceItem:
    claim_evidence_id: int
    stance: str
    declared_source_type: str
    source_type_reviewed: bool
    effective_tier: str
    tier_rank: int
    independence_key: str
    claim_supported: str


@dataclass(frozen=True)
class EvidenceSummary:
    items: list[EvidenceItem]
    strongest_effective_tier: str
    independent_source_count: int
    citation_count: int


def summarize_evidence(links: list) -> EvidenceSummary:
    items: list[EvidenceItem] = []
    for link in links:
        source = link.citation.source
        declared = source.source_type if isinstance(source.source_type, SourceType) else SourceType(source.source_type)
        reviewed = bool(getattr(source, "source_type_reviewed", False))
        effective = effective_source_type(declared, reviewed)
        stance = link.stance.value if isinstance(link.stance, EvidenceStance) else str(link.stance)
        items.append(
            EvidenceItem(
                claim_evidence_id=link.id,
                stance=stance,
                declared_source_type=declared.value,
                source_type_reviewed=reviewed,
                effective_tier=effective.value,
                tier_rank=TIER_RANK[effective],
                independence_key=independence_key(source),
                claim_supported=getattr(link, "claim_supported", "") or "",
            )
        )
    items.sort(key=lambda item: (-item.tier_rank, item.claim_evidence_id))
    strongest = items[0].effective_tier if items else SourceType.unknown.value
    independent = len({item.independence_key for item in items})
    return EvidenceSummary(
        items=items,
        strongest_effective_tier=strongest,
        independent_source_count=independent,
        citation_count=len(items),
    )
