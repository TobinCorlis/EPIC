from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class KnowledgeStatus(str, Enum):
    unverified = "unverified"
    candidate = "candidate"
    reviewed = "reviewed"
    verified = "verified"
    disputed = "disputed"
    retired = "retired"
    archived = "archived"


class ContradictionStatus(str, Enum):
    detected = "detected"
    reviewed = "reviewed"
    confirmed = "confirmed"
    dismissed = "dismissed"


class ResearchJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TopicDossier(Base):
    __tablename__ = "topic_dossiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(250), unique=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sources = relationship("DossierSource", back_populates="dossier", cascade="all, delete-orphan")
    knowledge_claims = relationship("KnowledgeClaim", back_populates="dossier", cascade="all, delete-orphan")
    jobs = relationship("ResearchJob", back_populates="dossier")


class DossierSource(Base):
    __tablename__ = "dossier_sources"
    __table_args__ = (UniqueConstraint("dossier_id", "source_id", name="uq_dossier_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dossier_id: Mapped[int] = mapped_column(ForeignKey("topic_dossiers.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dossier = relationship("TopicDossier", back_populates="sources")
    source = relationship("Source")


class KnowledgeClaim(Base):
    __tablename__ = "knowledge_claims"
    __table_args__ = (UniqueConstraint("dossier_id", "fingerprint", name="uq_dossier_claim_fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dossier_id: Mapped[int] = mapped_column(ForeignKey("topic_dossiers.id"), index=True)
    originating_claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    normalized_body: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[KnowledgeStatus] = mapped_column(SqlEnum(KnowledgeStatus), default=KnowledgeStatus.unverified)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dossier = relationship("TopicDossier", back_populates="knowledge_claims")
    originating_claim = relationship("Claim")
    contradictions_as_left = relationship(
        "ClaimContradiction", foreign_keys="ClaimContradiction.left_claim_id", back_populates="left_claim"
    )
    contradictions_as_right = relationship(
        "ClaimContradiction", foreign_keys="ClaimContradiction.right_claim_id", back_populates="right_claim"
    )


class ClaimContradiction(Base):
    __tablename__ = "claim_contradictions"
    __table_args__ = (UniqueConstraint("left_claim_id", "right_claim_id", name="uq_contradiction_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dossier_id: Mapped[int] = mapped_column(ForeignKey("topic_dossiers.id"), index=True)
    left_claim_id: Mapped[int] = mapped_column(ForeignKey("knowledge_claims.id"), index=True)
    right_claim_id: Mapped[int] = mapped_column(ForeignKey("knowledge_claims.id"), index=True)
    similarity_score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[ContradictionStatus] = mapped_column(
        SqlEnum(ContradictionStatus), default=ContradictionStatus.detected
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    left_claim = relationship("KnowledgeClaim", foreign_keys=[left_claim_id], back_populates="contradictions_as_left")
    right_claim = relationship("KnowledgeClaim", foreign_keys=[right_claim_id], back_populates="contradictions_as_right")


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dossier_id: Mapped[int | None] = mapped_column(ForeignKey("topic_dossiers.id"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[ResearchJobStatus] = mapped_column(
        SqlEnum(ResearchJobStatus), default=ResearchJobStatus.queued, index=True
    )
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str] = mapped_column(String(250), default="Queued")
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    dossier = relationship("TopicDossier", back_populates="jobs")
    events = relationship("ResearchJobEvent", back_populates="job", cascade="all, delete-orphan")


class ResearchJobEvent(Base):
    __tablename__ = "research_job_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("research_jobs.id"), index=True)
    progress_percent: Mapped[int] = mapped_column(Integer)
    step: Mapped[str] = mapped_column(String(250))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job = relationship("ResearchJob", back_populates="events")
