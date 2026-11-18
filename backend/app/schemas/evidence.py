from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models.evidence import EvidenceStance, SourceType


class SourceCreate(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    url: HttpUrl
    publisher: str | None = Field(default=None, max_length=300)
    author: str | None = Field(default=None, max_length=300)
    publication_date: datetime | None = None
    source_type: SourceType = SourceType.unknown


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    publisher: str | None
    author: str | None
    publication_date: datetime | None
    source_type: SourceType
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
    citation_id: int
    stance: EvidenceStance
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=2000)


class EvidenceLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_id: int
    citation_id: int
    stance: EvidenceStance
    relevance_score: float
    note: str | None
    created_at: datetime


class ClaimEvidenceSummary(BaseModel):
    claim_id: int
    supports_score: float
    contradicts_score: float
    contextual_score: float
    net_evidence_score: float
    citation_count: int
    citation_requirement_met: bool
