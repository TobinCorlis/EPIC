from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LibraryEntryCreate(BaseModel):
    question: str = Field(min_length=5)
    question_population: str | None = Field(default=None, max_length=300)
    question_timeframe: str | None = Field(default=None, max_length=300)
    question_geography: str | None = Field(default=None, max_length=300)
    question_metric: str | None = Field(default=None, max_length=300)
    direct_answer: Literal["yes", "no", "gap"]
    status: Literal["verified", "supported", "disputed", "unresolved"]
    facts: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    uncertainty: str | None = None
    supporting_claim_ids: list[int] = Field(min_length=1)
    source_ids: list[int] = []
    verification_event_ids: list[int] = []
    covered_points: list[str] = Field(min_length=1)
    change_log: str = Field(min_length=3)


class LibraryVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_number: int
    direct_answer: str
    status: str
    facts: str
    interpretation: str
    uncertainty: str | None
    date_resolved: datetime | None
    last_reviewed_at: datetime
    change_log: str
    outcome: str
    winning_source_id: int | None
    winning_reason: str | None
    created_at: datetime


class ReevaluationCreate(BaseModel):
    reason: str = Field(min_length=3)
    evidence_note: str | None = None
    new_source_id: int | None = None
    knowledge_claim_id: int | None = None
    claim_id: int | None = None


class ReevaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_id: int | None
    knowledge_claim_id: int | None
    claim_id: int | None
    reason: str
    evidence_note: str | None
    new_source_id: int | None
    requested_by_user_id: int
    requested_at: datetime
    status: str
    decision: str | None
    winning_source_id: int | None
    winning_reason: str | None
    decided_by_user_id: int | None
    decided_at: datetime | None
    resulting_version_id: int | None


class ReevaluationDecision(BaseModel):
    outcome: Literal["upheld", "revised", "overturned"]
    note: str = Field(min_length=3)
    direct_answer: Literal["yes", "no", "gap"] | None = None
    status: Literal["verified", "supported", "disputed", "unresolved"] | None = None
    facts: str | None = None
    interpretation: str | None = None
    uncertainty: str | None = None


class PointResolve(BaseModel):
    direct_answer: Literal["yes", "no", "gap"]
    status: Literal["supported", "disputed", "unresolved"]
    facts: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    uncertainty: str | None = None
    supporting_claim_ids: list[int] = Field(min_length=1)
    change_log: str = Field(min_length=3)


class InvalidationCreate(BaseModel):
    subject_type: Literal["source", "verification_event"]
    subject_id: int
    kind: Literal["false_information", "fabrication", "misconduct", "retraction", "error"]
    reason: str = Field(min_length=3)
    source_id: int


class LibraryEntryRead(BaseModel):
    id: int
    question: str
    question_population: str | None
    question_timeframe: str | None
    question_geography: str | None
    question_metric: str | None
    stale: bool
    reevaluation_pending: bool
    status_label: str | None
    current_version: LibraryVersionRead | None
    versions: list[LibraryVersionRead]
    supporting_claim_ids: list[int]
    source_ids: list[int]
    verification_event_ids: list[int]
    requests: list[ReevaluationRead]
    created_at: datetime
