from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.knowledge import ContradictionStatus, KnowledgeStatus, ResearchJobStatus


class DossierCreate(BaseModel):
    title: str = Field(min_length=3, max_length=250)
    question: str = Field(min_length=5)
    summary: str | None = None


class DossierRead(DossierCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class DossierSourceCreate(BaseModel):
    source_id: int
    note: str | None = None


class DossierSourceRead(DossierSourceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dossier_id: int
    added_at: datetime


class KnowledgeClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=3)
    originating_claim_id: int | None = None


class KnowledgeClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dossier_id: int
    body: str
    originating_claim_id: int | None = None
    normalized_body: str
    fingerprint: str
    status: KnowledgeStatus
    confidence_score: float
    created_at: datetime


class ClaimMatchRead(BaseModel):
    claim_id: int
    body: str
    similarity: float
    duplicate: bool
    contradiction_candidate: bool
    reason: str


class ContradictionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dossier_id: int
    left_claim_id: int
    right_claim_id: int
    similarity_score: float
    reason: str
    status: ContradictionStatus
    created_at: datetime


class ContradictionUpdate(BaseModel):
    status: ContradictionStatus


class ResearchJobCreate(BaseModel):
    query: str = Field(min_length=3)
    dossier_id: int | None = None


class ResearchJobUpdate(BaseModel):
    status: ResearchJobStatus | None = None
    progress_percent: int = Field(ge=0, le=100)
    current_step: str = Field(min_length=1, max_length=250)
    message: str | None = None
    result_summary: str | None = None
    error_message: str | None = None


class ResearchJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dossier_id: int | None
    query: str
    status: ResearchJobStatus
    progress_percent: int
    current_step: str
    result_summary: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ResearchJobEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    progress_percent: int
    step: str
    message: str | None
    created_at: datetime
