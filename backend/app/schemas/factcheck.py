from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=3, max_length=500)
    url: str | None = None
    document_reference: str | None = Field(default=None, max_length=1000)
    publisher: str | None = Field(default=None, max_length=300)
    author: str | None = Field(default=None, max_length=300)
    publication_date: datetime | None = None


class SourceCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int | None
    claim_id: int | None
    citation_id: int | None
    checker_name: str
    checker_version: str
    api_name: str
    query: str
    response_id: str | None
    result: str
    match_score: float | None
    http_status: int | None
    final_url: str | None
    content_type: str | None
    content_hash: str | None
    evidence_url: str | None
    archive_url: str | None
    archive_timestamp: str | None
    matched_snippet: str | None
    detail: str
    superseded: bool = False
    created_at: datetime


class VerificationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_type: str
    subject_id: int
    status: str
    attempt_count: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
