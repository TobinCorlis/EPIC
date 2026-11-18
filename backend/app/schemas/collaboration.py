from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.argument import DebateSide, ParticipantRole
from app.models.collaboration import InvitationStatus


class InvitationCreate(BaseModel):
    invited_email: EmailStr | None = None
    participant_role: ParticipantRole = ParticipantRole.debater
    side: DebateSide = DebateSide.neutral
    expires_in_hours: int = Field(default=72, ge=1, le=720)
    max_uses: int = Field(default=1, ge=1, le=100)


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    debate_id: int
    invited_email: str | None
    participant_role: str
    side: str
    status: InvitationStatus
    max_uses: int
    use_count: int
    expires_at: datetime
    created_at: datetime
    invite_token: str | None = None


class InvitationAccept(BaseModel):
    token: str
    display_name: str = Field(min_length=2, max_length=120)


class DebateEventRead(BaseModel):
    id: int
    debate_id: int
    event_type: str
    actor_user_id: int | None
    payload: dict
    created_at: datetime

class TurnCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    rebuttal_target_turn_id: int | None = None


class TurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    debate_id: int
    participant_id: int
    sequence_number: int
    body: str
    status: str
    started_at: datetime
    submitted_at: datetime


class RoomStateRead(BaseModel):
    debate_id: int
    current_participant_id: int | None
    turn_duration_seconds: int
    turn_started_at: datetime | None
    turn_sequence: int
    remaining_seconds: int | None


class RoomConfigure(BaseModel):
    turn_duration_seconds: int = Field(default=300, ge=30, le=7200)
    first_participant_id: int | None = None

class TurnPreview(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    rebuttal_target_turn_id: int | None = None


class TurnAnalysisRead(BaseModel):
    on_topic: bool
    pivot_detected: bool
    citation_required: bool
    citation_present: bool
    rebuttal_target_required: bool
    approved: bool
    reasons: list[str]


class ModerationReviewRead(BaseModel):
    id: int
    debate_id: int
    participant_id: int
    submitted_by_user_id: int
    body: str
    rebuttal_target_turn_id: int | None
    analysis: TurnAnalysisRead
    status: str
    moderator_user_id: int | None
    moderator_note: str | None
    created_at: datetime
    resolved_at: datetime | None


class ModerationDecision(BaseModel):
    approve: bool
    note: str = Field(min_length=2, max_length=2000)
