from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.argument import (
    ArgumentNodeType,
    ChallengeStatus,
    DebateSide,
    ParticipantRole,
    RulingOutcome,
    VerificationStatus,
)


class ParticipantCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    role: ParticipantRole = ParticipantRole.debater
    side: DebateSide = DebateSide.neutral


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    debate_id: int
    display_name: str
    user_id: int | None = None
    role: ParticipantRole
    side: DebateSide
    created_at: datetime


class ArgumentNodeCreate(BaseModel):
    participant_id: int
    claim_id: int | None = None
    parent_node_id: int | None = None
    node_type: ArgumentNodeType
    body: str = Field(min_length=2, max_length=10000)


class ArgumentNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    debate_id: int
    participant_id: int
    claim_id: int | None
    parent_node_id: int | None
    node_type: ArgumentNodeType
    side: DebateSide
    body: str
    verification_status: VerificationStatus
    created_at: datetime


class VerificationUpdate(BaseModel):
    verification_status: VerificationStatus


class EvidenceChallengeCreate(BaseModel):
    challenger_id: int
    reason: str = Field(min_length=5, max_length=4000)
    requested_remedy: str | None = Field(default=None, max_length=2000)


class EvidenceChallengeUpdate(BaseModel):
    status: ChallengeStatus
    response: str | None = Field(default=None, max_length=4000)


class EvidenceChallengeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_evidence_id: int
    challenger_id: int
    reason: str
    requested_remedy: str | None
    status: ChallengeStatus
    response: str | None
    created_at: datetime
    resolved_at: datetime | None


class ModeratorRulingCreate(BaseModel):
    moderator_id: int
    argument_node_id: int | None = None
    challenge_id: int | None = None
    outcome: RulingOutcome
    rationale: str = Field(min_length=5, max_length=6000)
    rule_reference: str | None = Field(default=None, max_length=250)

    @model_validator(mode="after")
    def require_target(self):
        if self.argument_node_id is None and self.challenge_id is None:
            raise ValueError("A ruling must target an argument node or an evidence challenge")
        return self


class ModeratorRulingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    debate_id: int
    moderator_id: int
    argument_node_id: int | None
    challenge_id: int | None
    outcome: RulingOutcome
    rationale: str
    rule_reference: str | None
    created_at: datetime
