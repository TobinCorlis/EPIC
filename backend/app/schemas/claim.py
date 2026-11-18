from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.claim import ClaimType


class ClaimCreate(BaseModel):
    body: str = Field(min_length=2)
    claim_type: ClaimType = ClaimType.factual


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    debate_id: int
    body: str
    claim_type: ClaimType
    citation_required: bool
    on_topic: bool
    moderation_note: str | None
    created_at: datetime
