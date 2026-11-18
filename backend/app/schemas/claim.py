from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.claim import ClaimType
from app.schemas.status_history import StatusHistoryRead


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
    status_notes: list[StatusHistoryRead] = []
    created_at: datetime
