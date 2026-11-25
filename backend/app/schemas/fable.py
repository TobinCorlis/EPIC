from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FableMatchupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=250)
    question: str = Field(min_length=5)
    mode: Literal["ai_matchup", "debate"]
    personal_knowledge_only: bool = True
    participants: list[str] = Field(min_length=2, max_length=8)


class FableParticipantRead(BaseModel):
    id: int
    name: str


class FableLoreCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_title: str = Field(min_length=1, max_length=300)
    installment: str = Field(min_length=1, max_length=300)
    pinpoint: str = Field(min_length=1, max_length=200)
    canon_status: Literal["primary_canon", "secondary", "non_canon"]
    body: str = Field(min_length=1)


class FableLoreRead(FableLoreCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class FableStepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(ge=1)
    body: str = Field(min_length=1)
    lore_item_ids: list[int] = Field(min_length=1)


class FableStepRead(BaseModel):
    id: int
    step_number: int
    body: str
    lore_item_ids: list[int]


class FableCanonNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["silent", "contradicts"]
    note: str = Field(min_length=3)


class FableCanonNoteRead(FableCanonNoteCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class FableMoveCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_id: int
    move_text: str = Field(min_length=1)
    claimed_source: str = Field(min_length=1)
    lore_item_id: int | None = None


class FableRulingCreate(BaseModel):
    """Rules one move already made. A counter or a new fact is not a field here."""

    model_config = ConfigDict(extra="forbid")

    ruling: Literal["allowed", "disallowed", "unverified"]
    reason: str = Field(min_length=3)
    citation: str = Field(min_length=1)


class FableMoveRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    matchup_id: int
    participant_id: int
    move_text: str
    claimed_source: str
    lore_item_id: int | None
    ruling: str | None
    reason: str | None
    citation: str | None
    ruled_by: str | None
    created_at: datetime


class FableDebateOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=3)
    move_ids: list[int] = Field(min_length=1)


class FableMatchupRead(BaseModel):
    id: int
    title: str
    question: str
    mode: str
    fiction: bool = True
    personal_knowledge_only: bool
    participants: list[FableParticipantRead]
    lore: list[FableLoreRead]
    steps: list[FableStepRead]
    canon_notes: list[FableCanonNoteRead]
    moves: list[FableMoveRead]
    ai_outcome: str | None
    ai_outcome_note: str | None
    ai_outcome_label: str = "ai_matchup"
    debate_outcome: str | None
    debate_outcome_note: str | None
    debate_outcome_move_ids: list[int]
    debate_outcome_label: str = "debate"
    automated_analysis: str
    automated_referee: str
    referee_scope: str
    cheating_notice: str
    created_at: datetime
