from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ClaimType(str, Enum):
    factual = "factual"
    inferential = "inferential"
    opinion = "opinion"


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[ClaimType] = mapped_column(SqlEnum(ClaimType), default=ClaimType.factual)
    citation_required: Mapped[bool] = mapped_column(Boolean, default=True)
    on_topic: Mapped[bool] = mapped_column(Boolean, default=True)
    moderation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    debate = relationship("Debate", back_populates="claims")
    evidence_links = relationship("ClaimEvidence", back_populates="claim", cascade="all, delete-orphan")
    argument_nodes = relationship("ArgumentNode", back_populates="claim")
