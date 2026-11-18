from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VerificationSubject(str, Enum):
    argument_node = "argument_node"
    knowledge_claim = "knowledge_claim"


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    actor = relationship("User")
