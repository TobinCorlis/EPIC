from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.database import Base

SCOPE_FIELDS = ("population", "timeframe", "geography", "metric")


class ScopeReviewFlag(Base):
    """A rule-based review flag. It is not a finding that the evidence is false."""

    __tablename__ = "scope_review_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    claim_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("claim_evidence.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    dimension: Mapped[str] = mapped_column(String(40))
    source_text: Mapped[str] = mapped_column(Text)
    claim_text: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
