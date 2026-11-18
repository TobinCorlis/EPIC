from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.database import Base


class ReferenceEntry(Base):
    """One precise question. Versions hold the answers; this row is never overwritten."""

    __tablename__ = "reference_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    question_population: Mapped[str | None] = mapped_column(String(300), nullable=True)
    question_timeframe: Mapped[str | None] = mapped_column(String(300), nullable=True)
    question_geography: Mapped[str | None] = mapped_column(String(300), nullable=True)
    question_metric: Mapped[str | None] = mapped_column(String(300), nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    reevaluation_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReferenceEntryVersion(Base):
    __tablename__ = "reference_entry_versions"
    __table_args__ = (UniqueConstraint("entry_id", "version_number", name="uq_entry_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("reference_entries.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    direct_answer: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20))
    facts: Mapped[str] = mapped_column(Text)
    interpretation: Mapped[str] = mapped_column(Text)
    uncertainty: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_resolved: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    change_log: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(20), default="initial")
    winning_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    winning_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReferenceEntryClaim(Base):
    __tablename__ = "reference_entry_claims"
    __table_args__ = (UniqueConstraint("entry_id", "claim_id", name="uq_entry_claim"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("reference_entries.id"), index=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)


class ReferenceEntrySource(Base):
    __tablename__ = "reference_entry_sources"
    __table_args__ = (UniqueConstraint("entry_id", "source_id", name="uq_entry_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("reference_entries.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)


class ReferenceEntryVerification(Base):
    __tablename__ = "reference_entry_verifications"
    __table_args__ = (UniqueConstraint("entry_id", "verification_event_id", name="uq_entry_verification"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("reference_entries.id"), index=True)
    verification_event_id: Mapped[int] = mapped_column(ForeignKey("verification_events.id"), index=True)


class ReferenceEntryDebate(Base):
    __tablename__ = "reference_entry_debates"
    __table_args__ = (UniqueConstraint("entry_id", "debate_id", name="uq_entry_debate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("reference_entries.id"), index=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    served: Mapped[bool] = mapped_column(Boolean, default=False)


class LibraryPoint(Base):
    __tablename__ = "library_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("reference_entries.id"), index=True)
    debate_id: Mapped[int | None] = mapped_column(ForeignKey("debates.id"), nullable=True, index=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True, index=True)
    argument_node_id: Mapped[int | None] = mapped_column(ForeignKey("argument_nodes.id"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(80))
    covered_by_version_id: Mapped[int | None] = mapped_column(ForeignKey("reference_entry_versions.id"), nullable=True)
    research_job_id: Mapped[int | None] = mapped_column(ForeignKey("research_jobs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReevaluationRequest(Base):
    __tablename__ = "reevaluation_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("reference_entries.id"), nullable=True, index=True)
    knowledge_claim_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_claims.id"), nullable=True, index=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="open")
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    winning_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    winning_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resulting_version_id: Mapped[int | None] = mapped_column(ForeignKey("reference_entry_versions.id"), nullable=True)


class UpstreamInvalidation(Base):
    """A recorded finding that a source or verification rested on false information."""

    __tablename__ = "upstream_invalidations"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    recorded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
