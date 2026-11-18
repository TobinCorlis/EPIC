from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StatusHistory(Base):
    """Visible record of a status change.

    Legacy rc2 labels that were not backed by a verification event are kept
    here instead of being deleted. Later overturns can point at the event.
    """

    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(40), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    previous_status: Mapped[str] = mapped_column(String(40))
    new_status: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)
    verification_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("verification_events.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    verification_event = relationship("VerificationEvent")
