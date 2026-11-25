from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.claim import ClaimType
from app.schemas.status_history import StatusHistoryRead


class CorrectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_body: str
    corrected_body: str
    reason: str
    kind: str = "text"
    author_user_id: int
    created_at: datetime


class ClaimCreate(BaseModel):
    body: str = Field(min_length=2)
    claim_type: ClaimType = ClaimType.factual
    uncertainty: str | None = Field(default=None, max_length=4000)
    scope_population: str | None = Field(default=None, max_length=300)
    scope_timeframe: str | None = Field(default=None, max_length=300)
    scope_geography: str | None = Field(default=None, max_length=300)
    scope_metric: str | None = Field(default=None, max_length=300)
    answerability: Literal["factual", "not_factually_answerable"] = "factual"
    answerability_reason: str | None = None

    @model_validator(mode="after")
    def reason_when_unanswerable(self):
        if self.answerability == "not_factually_answerable" and not (self.answerability_reason or "").strip():
            raise ValueError("A reason is required when a claim is not factually answerable")
        return self


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    debate_id: int
    body: str
    claim_type: ClaimType
    citation_required: bool
    on_topic: bool
    needs_review: bool = False
    moderation_note: str | None
    uncertainty: str | None = None
    scope_population: str | None = None
    scope_timeframe: str | None = None
    scope_geography: str | None = None
    scope_metric: str | None = None
    answerability: str = "factual"
    answerability_reason: str | None = None
    corrections: list[CorrectionRead] = []
    status_notes: list[StatusHistoryRead] = []
    library_entry_id: int | None = None
    library_point_id: int | None = None
    library_point_status: str | None = None
    library_notice: str | None = None
    reevaluation_pending: bool = False
    created_at: datetime


class CorrectionCreate(BaseModel):
    corrected_body: str = Field(min_length=2, max_length=10000)
    reason: str = Field(min_length=3, max_length=4000)
    uncertainty: str | None = Field(default=None, max_length=4000)
