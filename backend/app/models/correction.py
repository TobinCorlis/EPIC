from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.clock import utcnow


class ClaimCorrection(Base):
    """Links the text that was corrected to the replacement, with reason and author."""

    __tablename__ = "claim_corrections"
    __table_args__ = (
        CheckConstraint(
            "(claim_id IS NOT NULL AND knowledge_claim_id IS NULL) "
            "OR (claim_id IS NULL AND knowledge_claim_id IS NOT NULL)",
            name="ck_correction_one_subject",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True, index=True)
    knowledge_claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_claims.id"), nullable=True, index=True
    )
    original_body: Mapped[str] = mapped_column(Text)
    corrected_body: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    claim = relationship("Claim", back_populates="corrections")
    knowledge_claim = relationship("KnowledgeClaim", back_populates="corrections")
    author = relationship("User")
