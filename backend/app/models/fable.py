"""EPIC FABLE is fiction. These rows are not sources, claims, or library entries."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.database import Base

AUTOMATED_FABLE = "not_implemented"
CHEATING_NOTICE = (
    "EPIC cannot fully prevent a debater from consulting material outside this room. "
    "The record shows only what was submitted and ruled here."
)


class FableMatchup(Base):
    __tablename__ = "fable_matchups"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(250))
    question: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(40))
    personal_knowledge_only: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_outcome: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    debate_outcome: Mapped[str | None] = mapped_column(String(80), nullable=True)
    debate_outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    debate_outcome_move_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    automated_analysis: Mapped[str] = mapped_column(String(40), default=AUTOMATED_FABLE)
    automated_referee: Mapped[str] = mapped_column(String(40), default=AUTOMATED_FABLE)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FableParticipant(Base):
    __tablename__ = "fable_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("fable_matchups.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))


class FableLoreItem(Base):
    __tablename__ = "fable_lore_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("fable_matchups.id"), index=True)
    work_title: Mapped[str] = mapped_column(String(300))
    installment: Mapped[str] = mapped_column(String(300))
    pinpoint: Mapped[str] = mapped_column(String(200))
    canon_status: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)


class FableReasoningStep(Base):
    __tablename__ = "fable_reasoning_steps"
    __table_args__ = (UniqueConstraint("matchup_id", "step_number", name="uq_fable_step_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("fable_matchups.id"), index=True)
    step_number: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)


class FableStepLore(Base):
    __tablename__ = "fable_step_lore"
    __table_args__ = (UniqueConstraint("step_id", "lore_item_id", name="uq_fable_step_lore"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("fable_reasoning_steps.id"), index=True)
    lore_item_id: Mapped[int] = mapped_column(ForeignKey("fable_lore_items.id"), index=True)


class FableCanonNote(Base):
    __tablename__ = "fable_canon_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("fable_matchups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)


class FableMove(Base):
    __tablename__ = "fable_moves"

    id: Mapped[int] = mapped_column(primary_key=True)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("fable_matchups.id"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("fable_participants.id"), index=True)
    move_text: Mapped[str] = mapped_column(Text)
    claimed_source: Mapped[str] = mapped_column(Text)
    lore_item_id: Mapped[int | None] = mapped_column(ForeignKey("fable_lore_items.id"), nullable=True)
    ruling: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    citation: Mapped[str | None] = mapped_column(Text, nullable=True)
    ruled_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ruled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
