from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DebateSide(str, Enum):
    affirmative = "affirmative"
    negative = "negative"
    neutral = "neutral"


class ParticipantRole(str, Enum):
    debater = "debater"
    moderator = "moderator"
    observer = "observer"
    ai_assistant = "ai_assistant"


class ArgumentNodeType(str, Enum):
    premise = "premise"
    conclusion = "conclusion"
    rebuttal = "rebuttal"
    concession = "concession"


class VerificationStatus(str, Enum):
    unverified = "unverified"
    unreviewed = "unreviewed"
    pending = "pending"
    verified = "verified"
    disputed = "disputed"
    rejected = "rejected"
    archived = "archived"


class ChallengeStatus(str, Enum):
    open = "open"
    answered = "answered"
    upheld = "upheld"
    denied = "denied"
    withdrawn = "withdrawn"


class RulingOutcome(str, Enum):
    allowed = "allowed"
    warning = "warning"
    revision_required = "revision_required"
    excluded = "excluded"
    challenge_upheld = "challenge_upheld"
    challenge_denied = "challenge_denied"


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("debate_id", "display_name", name="uq_debate_participant_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    role: Mapped[ParticipantRole] = mapped_column(SqlEnum(ParticipantRole), default=ParticipantRole.debater)
    side: Mapped[DebateSide] = mapped_column(SqlEnum(DebateSide), default=DebateSide.neutral)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    debate = relationship("Debate", back_populates="participants")
    argument_nodes = relationship("ArgumentNode", back_populates="participant")
    challenges = relationship("EvidenceChallenge", back_populates="challenger")
    rulings = relationship("ModeratorRuling", back_populates="moderator")


class ArgumentNode(Base):
    __tablename__ = "argument_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True, index=True)
    parent_node_id: Mapped[int | None] = mapped_column(ForeignKey("argument_nodes.id"), nullable=True, index=True)
    node_type: Mapped[ArgumentNodeType] = mapped_column(SqlEnum(ArgumentNodeType))
    side: Mapped[DebateSide] = mapped_column(SqlEnum(DebateSide))
    body: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SqlEnum(VerificationStatus), default=VerificationStatus.unverified
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    debate = relationship("Debate", back_populates="argument_nodes")
    participant = relationship("Participant", back_populates="argument_nodes")
    claim = relationship("Claim", back_populates="argument_nodes")
    parent = relationship("ArgumentNode", remote_side=[id], back_populates="children")
    children = relationship("ArgumentNode", back_populates="parent")
    rulings = relationship("ModeratorRuling", back_populates="argument_node")


class EvidenceChallenge(Base):
    __tablename__ = "evidence_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_evidence_id: Mapped[int] = mapped_column(ForeignKey("claim_evidence.id"), index=True)
    challenger_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    requested_remedy: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ChallengeStatus] = mapped_column(SqlEnum(ChallengeStatus), default=ChallengeStatus.open)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    evidence_link = relationship("ClaimEvidence", back_populates="challenges")
    challenger = relationship("Participant", back_populates="challenges")
    rulings = relationship("ModeratorRuling", back_populates="challenge")


class ModeratorRuling(Base):
    __tablename__ = "moderator_rulings"

    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id"), index=True)
    moderator_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    argument_node_id: Mapped[int | None] = mapped_column(ForeignKey("argument_nodes.id"), nullable=True, index=True)
    challenge_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_challenges.id"), nullable=True, index=True)
    outcome: Mapped[RulingOutcome] = mapped_column(SqlEnum(RulingOutcome))
    rationale: Mapped[str] = mapped_column(Text)
    rule_reference: Mapped[str | None] = mapped_column(String(250), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    debate = relationship("Debate", back_populates="rulings")
    moderator = relationship("Participant", back_populates="rulings")
    argument_node = relationship("ArgumentNode", back_populates="rulings")
    challenge = relationship("EvidenceChallenge", back_populates="rulings")
