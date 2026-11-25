from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.clock import utcnow


class DebateStatus(str, Enum):
    draft = "draft"
    open = "open"
    paused = "paused"
    concluded = "concluded"
    factually_concluded = "factually_concluded"


class Debate(Base):
    __tablename__ = "debates"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(250), index=True)
    fixed_question: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_population: Mapped[str | None] = mapped_column(String(300), nullable=True)
    question_timeframe: Mapped[str | None] = mapped_column(String(300), nullable=True)
    question_geography: Mapped[str | None] = mapped_column(String(300), nullable=True)
    question_metric: Mapped[str | None] = mapped_column(String(300), nullable=True)
    answerability: Mapped[str] = mapped_column(String(40), default="factual")
    answerability_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[DebateStatus] = mapped_column(SqlEnum(DebateStatus), default=DebateStatus.draft)
    library_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner = relationship("User", back_populates="owned_debates")
    claims = relationship("Claim", back_populates="debate", cascade="all, delete-orphan")
    participants = relationship("Participant", back_populates="debate", cascade="all, delete-orphan")
    argument_nodes = relationship("ArgumentNode", back_populates="debate", cascade="all, delete-orphan")
    rulings = relationship("ModeratorRuling", back_populates="debate", cascade="all, delete-orphan")
