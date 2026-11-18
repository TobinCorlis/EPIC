from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.clock import utcnow


class VerificationSubject(str, Enum):
    argument_node = "argument_node"
    knowledge_claim = "knowledge_claim"
    source = "source"


class RecordedVerificationStatus(str, Enum):
    verified = "verified"
    archived = "archived"


class VerificationEvent(Base):
    """A recorded decision that a subject is verified or archived.

    verified and archived are not client-settable statuses. They are written
    only when this row exists, with the actor, time, method, and evidence.
    """

    __tablename__ = "verification_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[VerificationSubject] = mapped_column(SqlEnum(VerificationSubject), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    result_status: Mapped[RecordedVerificationStatus] = mapped_column(SqlEnum(RecordedVerificationStatus))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    method: Mapped[str] = mapped_column(String(200))
    archive_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mistake_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mistake_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mistake_recorded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    actor = relationship("User", foreign_keys=[actor_user_id])
