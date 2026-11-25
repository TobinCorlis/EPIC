from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.models.evidence import EvidenceStance, SourceType, SourceVerificationStatus


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=500)
    url: HttpUrl | None = None
    document_reference: str | None = Field(default=None, max_length=1000)
    publisher: str | None = Field(default=None, max_length=300)
    author: str | None = Field(default=None, max_length=300)
    publication_date: datetime | None = None
    source_type: SourceType = SourceType.unknown
    scope_population: str | None = Field(default=None, max_length=300)
    scope_timeframe: str | None = Field(default=None, max_length=300)
    scope_geography: str | None = Field(default=None, max_length=300)
    scope_metric: str | None = Field(default=None, max_length=300)
    scope_study_type: str | None = Field(default=None, max_length=80)
    scope_sample_size: int | None = None

    @model_validator(mode="after")
    def require_url_or_document(self):
        document = (self.document_reference or "").strip()
        self.document_reference = document or None
        if self.url is None and self.document_reference is None:
            raise ValueError("A source requires a URL or a document reference")
        return self


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str | None
    document_reference: str | None
    publisher: str | None
    author: str | None
    publication_date: datetime | None
    source_type: SourceType
    source_type_reviewed: bool
    scope_population: str | None = None
    scope_timeframe: str | None = None
    scope_geography: str | None = None
    scope_metric: str | None = None
    scope_study_type: str | None = None
    scope_sample_size: int | None = None
    source_type_reviewed_by_user_id: int | None
    source_type_reviewed_at: datetime | None
    verification_status: SourceVerificationStatus
    record_status: str = "not_checked"
    record_note: str | None = None
    archive_url: str | None
    archived_at: datetime | None
    quality_score: float
    quality_rationale: str
    created_at: datetime


class CitationCreate(BaseModel):
    source_id: int
    locator: str | None = Field(default=None, max_length=250)
    excerpt: str | None = Field(default=None, max_length=4000)


class CitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    locator: str | None
    excerpt: str | None
    accessed_at: datetime


class EvidenceLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: int
    stance: EvidenceStance
    claim_supported: str = Field(min_length=1, max_length=4000)
    scope_population: str | None = Field(default=None, max_length=300)
    scope_timeframe: str | None = Field(default=None, max_length=300)
    scope_geography: str | None = Field(default=None, max_length=300)
    scope_metric: str | None = Field(default=None, max_length=300)
    scope_study_type: str | None = Field(default=None, max_length=80)
    scope_sample_size: int | None = None
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=2000)


class EvidenceLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_id: int
    citation_id: int
    stance: EvidenceStance
    claim_supported: str
    relevance_score: float
    note: str | None
    created_at: datetime


class EvidenceItemRead(BaseModel):
    claim_evidence_id: int
    stance: EvidenceStance
    declared_source_type: SourceType
    source_type_reviewed: bool
    effective_tier: str
    tier_rank: int
    independence_key: str
    claim_supported: str
    source_id: int | None = None
    source_title: str | None = None
    scope_population: str | None = None
    scope_timeframe: str | None = None
    scope_geography: str | None = None
    scope_metric: str | None = None
    scope_study_type: str | None = None
    scope_sample_size: int | None = None


class ConfidenceFactorRead(BaseModel):
    name: str
    value: float | None
    detail: str


class ConfidenceAssessmentRead(BaseModel):
    claim_id: int
    confidence_score: float | None
    label: str | None = None
    not_factually_answerable: bool = False
    answerability_reason: str | None = None
    scale: str | None = "0–1"
    cited_source_note: str | None = None
    contradicting_sources: list[dict] = []
    factors: list[ConfidenceFactorRead]
    automated_source_check: str
    automated_source_check_detail: str


class ScopeFlagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_evidence_id: int | None = None
    kind: str
    dimension: str
    source_text: str
    claim_text: str
    note: str


class ClaimEvidenceSummary(BaseModel):
    claim_id: int
    items: list[EvidenceItemRead]
    strongest_effective_tier: str
    independent_source_count: int
    citation_count: int
    citation_requirement_met: bool
    confidence: ConfidenceAssessmentRead | None = None
    scope_flags: list[ScopeFlagRead] = []
    scope_check: str = (
        "Rule-based comparison of user-entered scope fields. A flag means needs review, not rejection."
    )


class SourceTypeReview(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


class SourceRecordReview(BaseModel):
    status: Literal["found", "no_record_found"]
    note: str = Field(min_length=3, max_length=1000)
