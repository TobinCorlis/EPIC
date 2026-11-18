from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class InvitationStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"
    expired = "expired"


class DebateInvitation(Base):
    __tablename__ = "debate_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    participant_role: Mapped[str] = mapped_column(String(40), default="debater")
    side: Mapped[str] = mapped_column(String(40), default="neutral")
    status: Mapped[InvitationStatus] = mapped_column(SqlEnum(InvitationStatus), default=InvitationStatus.pending, index=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DebateEvent(Base):
    __tablename__ = "debate_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class TurnStatus(str, Enum):
    active = "active"
    completed = "completed"
    skipped = "skipped"
    expired = "expired"


class DebateTurn(Base):
    __tablename__ = "debate_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, index=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[TurnStatus] = mapped_column(SqlEnum(TurnStatus), default=TurnStatus.completed, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DebateRoomState(Base):
    __tablename__ = "debate_room_states"

    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), primary_key=True)
    current_participant_id: Mapped[int | None] = mapped_column(ForeignKey("participants.id"), nullable=True, index=True)
    turn_duration_seconds: Mapped[int] = mapped_column(Integer, default=300)
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    turn_sequence: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ModerationReviewStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TurnModerationReview(Base):
    __tablename__ = "turn_moderation_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    submitted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    rebuttal_target_turn_id: Mapped[int | None] = mapped_column(ForeignKey("debate_turns.id"), nullable=True)
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[ModerationReviewStatus] = mapped_column(SqlEnum(ModerationReviewStatus), default=ModerationReviewStatus.pending, index=True)
    moderator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    moderator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
