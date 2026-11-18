from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.database import Base


class ClaimConfidenceAssessment(Base):
    """Stored factor breakdown for one debate claim. Not a verification."""

    __tablename__ = "claim_confidence_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), unique=True, index=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    breakdown_json: Mapped[str] = mapped_column(Text)
    automated_source_check: Mapped[str] = mapped_column(String(40), default="not_implemented")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
