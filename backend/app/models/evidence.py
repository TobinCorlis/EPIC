from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SourceType(str, Enum):
    primary_law = "primary_law"
    government_record = "government_record"
    peer_reviewed = "peer_reviewed"
    official_data = "official_data"
    reputable_news = "reputable_news"
    expert_analysis = "expert_analysis"
    advocacy = "advocacy"
    user_generated = "user_generated"
    unknown = "unknown"


class EvidenceStance(str, Enum):
    supports = "supports"
    contradicts = "contradicts"
    contextualizes = "contextualizes"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    publisher: Mapped[str | None] = mapped_column(String(300), nullable=True)
    author: Mapped[str | None] = mapped_column(String(300), nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_type: Mapped[SourceType] = mapped_column(SqlEnum(SourceType), default=SourceType.unknown)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    quality_rationale: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    citations = relationship("Citation", back_populates="source", cascade="all, delete-orphan")


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    locator: Mapped[str | None] = mapped_column(String(250), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    source = relationship("Source", back_populates="citations")
    claim_links = relationship("ClaimEvidence", back_populates="citation", cascade="all, delete-orphan")


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (UniqueConstraint("claim_id", "citation_id", name="uq_claim_citation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    citation_id: Mapped[int] = mapped_column(ForeignKey("citations.id"), index=True)
    stance: Mapped[EvidenceStance] = mapped_column(SqlEnum(EvidenceStance))
    relevance_score: Mapped[float] = mapped_column(Float, default=0.5)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    claim = relationship("Claim", back_populates="evidence_links")
    citation = relationship("Citation", back_populates="claim_links")
    challenges = relationship("EvidenceChallenge", back_populates="evidence_link", cascade="all, delete-orphan")
