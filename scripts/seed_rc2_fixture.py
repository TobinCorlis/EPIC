"""Seed a realistic v1.0-rc2 database.

Run this only with the unmodified baseline tree imported as ``app``.
``verify_release.py`` sets PYTHONPATH to a worktree of that commit.
The current application models are not a compatible target.
"""
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.argument import (
    ArgumentNode,
    ArgumentNodeType,
    ChallengeStatus,
    DebateSide,
    EvidenceChallenge,
    ModeratorRuling,
    Participant,
    ParticipantRole,
    RulingOutcome,
    VerificationStatus,
)
from app.models.auth import AuthSession, User, UserRole
from app.models.claim import Claim, ClaimType
from app.models.collaboration import (
    DebateEvent,
    DebateInvitation,
    DebateRoomState,
    DebateTurn,
    InvitationStatus,
    TurnModerationReview,
    TurnStatus,
)
from app.models.debate import Debate, DebateStatus
from app.models.evidence import Citation, ClaimEvidence, EvidenceStance, Source, SourceType
from app.models.knowledge import (
    ClaimContradiction,
    ContradictionStatus,
    DossierSource,
    KnowledgeClaim,
    KnowledgeStatus,
    ResearchJob,
    ResearchJobEvent,
    ResearchJobStatus,
    TopicDossier,
)
from app.services.knowledge_matching import fingerprint_claim, normalize_claim

NOW = datetime(2026, 7, 31, 12, 0, 0)


def main() -> None:
    db = SessionLocal()
    member = User(
        email="member@example.gov",
        display_name="Member Researcher",
        password_hash=hash_password("verysecure123"),
        role=UserRole.member,
        created_at=NOW,
    )
    moderator = User(
        email="moderator@example.gov",
        display_name="Room Moderator",
        password_hash=hash_password("verysecure123"),
        role=UserRole.moderator,
        created_at=NOW,
    )
    admin = User(
        email="admin@example.gov",
        display_name="Platform Admin",
        password_hash=hash_password("verysecure123"),
        role=UserRole.administrator,
        created_at=NOW,
    )
    db.add_all([member, moderator, admin])
    db.flush()
    db.add(AuthSession(user_id=member.id, token_hash="a" * 64, expires_at=NOW + timedelta(days=7), created_at=NOW))

    debate = Debate(
        title="Grid reliability record",
        fixed_question="Do the cited records establish that storage kept the renewable grid reliable?",
        description="Seeded rc2 debate.",
        owner_user_id=member.id,
        status=DebateStatus.open,
        created_at=NOW,
    )
    db.add(debate)
    db.flush()

    factual = Claim(
        debate_id=debate.id,
        body="The agency report records 12 hours of storage coverage.",
        claim_type=ClaimType.factual,
        citation_required=True,
        on_topic=True,
        created_at=NOW,
    )
    inferential = Claim(
        debate_id=debate.id,
        body="Storage coverage of that length makes a renewable-heavy grid reliable.",
        claim_type=ClaimType.inferential,
        citation_required=True,
        on_topic=True,
        created_at=NOW,
    )
    opinion = Claim(
        debate_id=debate.id,
        body="Reliability should be valued above the speed of the transition.",
        claim_type=ClaimType.opinion,
        citation_required=False,
        on_topic=True,
        moderation_note=None,
        created_at=NOW,
    )
    db.add_all([factual, inferential, opinion])
    db.flush()

    agency = Source(
        title="Agency reliability report",
        url="https://example.gov/reliability-2024",
        publisher="Example Agency",
        author="Records Office",
        source_type=SourceType.government_record,
        quality_score=0.95,
        quality_rationale="Base score for government_record.",
        created_at=NOW,
    )
    blog = Source(
        title="Personal energy blog",
        url="https://blog.example/storage-hot-take",
        publisher="Example Blog",
        author="A. Writer",
        source_type=SourceType.user_generated,
        quality_score=0.35,
        quality_rationale="Base score for user_generated.",
        created_at=NOW,
    )
    db.add_all([agency, blog])
    db.flush()
    agency_citation = Citation(source_id=agency.id, locator="p. 14", excerpt="Storage covered 12 hours.", accessed_at=NOW)
    blog_citation = Citation(source_id=blog.id, locator=None, excerpt="I think storage solves this.", accessed_at=NOW)
    db.add_all([agency_citation, blog_citation])
    db.flush()
    support = ClaimEvidence(
        claim_id=factual.id,
        citation_id=agency_citation.id,
        stance=EvidenceStance.supports,
        relevance_score=0.8,
        note="Page 14 states the hour count.",
        created_at=NOW,
    )
    contradict = ClaimEvidence(
        claim_id=inferential.id,
        citation_id=blog_citation.id,
        stance=EvidenceStance.contradicts,
        relevance_score=0.3,
        note=None,
        created_at=NOW,
    )
    db.add_all([support, contradict])
    db.flush()

    debater = Participant(
        debate_id=debate.id,
        display_name="Affirmative Debater",
        user_id=member.id,
        role=ParticipantRole.debater,
        side=DebateSide.affirmative,
        created_at=NOW,
    )
    moderator_participant = Participant(
        debate_id=debate.id,
        display_name="Human Moderator",
        user_id=moderator.id,
        role=ParticipantRole.moderator,
        side=DebateSide.neutral,
        created_at=NOW,
    )
    db.add_all([debater, moderator_participant])
    db.flush()

    verified_node = ArgumentNode(
        debate_id=debate.id,
        participant_id=debater.id,
        claim_id=factual.id,
        node_type=ArgumentNodeType.premise,
        side=DebateSide.affirmative,
        body="The agency page is direct evidence of the hour count.",
        verification_status=VerificationStatus.verified,
        created_at=NOW,
    )
    pending_node = ArgumentNode(
        debate_id=debate.id,
        participant_id=debater.id,
        parent_node_id=None,
        node_type=ArgumentNodeType.conclusion,
        side=DebateSide.affirmative,
        body="Therefore the grid remained reliable.",
        verification_status=VerificationStatus.pending,
        created_at=NOW,
    )
    db.add_all([verified_node, pending_node])
    db.flush()
    pending_node.parent_node_id = verified_node.id
    db.add(
        ModeratorRuling(
            debate_id=debate.id,
            moderator_id=moderator_participant.id,
            argument_node_id=verified_node.id,
            outcome=RulingOutcome.allowed,
            rationale="The premise is on topic and linked to a factual claim.",
            rule_reference="EPIC-ARG-1",
            created_at=NOW,
        )
    )
    challenge = EvidenceChallenge(
        claim_evidence_id=support.id,
        challenger_id=debater.id,
        reason="The excerpt omits the footnote on the same page.",
        requested_remedy="Treat the excerpt as incomplete.",
        status=ChallengeStatus.open,
        created_at=NOW,
    )
    db.add(challenge)
    db.flush()
    db.add(
        ModeratorRuling(
            debate_id=debate.id,
            moderator_id=moderator_participant.id,
            challenge_id=challenge.id,
            outcome=RulingOutcome.challenge_denied,
            rationale="The footnote does not change the hour count.",
            created_at=NOW,
        )
    )

    dossier = TopicDossier(
        title="Renewable grid reliability",
        question="Can a renewable-heavy grid remain reliable?",
        summary="Seeded dossier.",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(dossier)
    db.flush()
    db.add(DossierSource(dossier_id=dossier.id, source_id=agency.id, note="Primary agency report.", added_at=NOW))
    verified_body = "The agency report records 12 hours of storage coverage."
    candidate_body = "A renewable-heavy grid can remain reliable with storage."
    verified_claim = KnowledgeClaim(
        dossier_id=dossier.id,
        originating_claim_id=factual.id,
        body=verified_body,
        normalized_body=normalize_claim(verified_body),
        fingerprint=fingerprint_claim(verified_body),
        status=KnowledgeStatus.verified,
        confidence_score=1.0,
        created_at=NOW,
    )
    candidate_claim = KnowledgeClaim(
        dossier_id=dossier.id,
        body=candidate_body,
        normalized_body=normalize_claim(candidate_body),
        fingerprint=fingerprint_claim(candidate_body),
        status=KnowledgeStatus.candidate,
        confidence_score=0.0,
        created_at=NOW,
    )
    db.add_all([verified_claim, candidate_claim])
    db.flush()
    db.add(
        ClaimContradiction(
            dossier_id=dossier.id,
            left_claim_id=verified_claim.id,
            right_claim_id=candidate_claim.id,
            similarity_score=0.4,
            reason="Different scope; kept as a candidate pair.",
            status=ContradictionStatus.detected,
            created_at=NOW,
        )
    )
    completed = ResearchJob(
        dossier_id=dossier.id,
        query="Find official grid reliability studies",
        status=ResearchJobStatus.completed,
        progress_percent=100,
        current_step="Completed",
        result_summary="Research workflow completed. Review linked sources, matches, and contradiction candidates.",
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
        worker_id="seed-worker",
        attempt_count=1,
    )
    queued = ResearchJob(
        dossier_id=dossier.id,
        query="Compare the agency hour count with the hearing transcript",
        status=ResearchJobStatus.queued,
        progress_percent=0,
        current_step="Queued",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add_all([completed, queued])
    db.flush()
    db.add(
        ResearchJobEvent(
            job_id=completed.id,
            progress_percent=100,
            step="Completed",
            message="Completed",
            created_at=NOW,
        )
    )

    db.add(
        DebateInvitation(
            debate_id=debate.id,
            created_by_user_id=member.id,
            token_hash="b" * 64,
            invited_email="guest@example.gov",
            participant_role="debater",
            side="negative",
            status=InvitationStatus.pending,
            max_uses=1,
            use_count=0,
            expires_at=NOW + timedelta(days=2),
            created_at=NOW,
        )
    )
    db.add(
        DebateEvent(
            debate_id=debate.id,
            event_type="debate.opened",
            actor_user_id=member.id,
            payload_json='{"seed": true}',
            created_at=NOW,
        )
    )
    db.add(
        DebateRoomState(
            debate_id=debate.id,
            current_participant_id=debater.id,
            turn_duration_seconds=300,
            turn_started_at=NOW,
            turn_sequence=1,
            updated_at=NOW,
        )
    )
    db.add(
        DebateTurn(
            debate_id=debate.id,
            participant_id=debater.id,
            sequence_number=1,
            body="The report shows a 12 hour storage figure.",
            status=TurnStatus.completed,
            started_at=NOW,
            submitted_at=NOW,
        )
    )
    db.add(
        TurnModerationReview(
            debate_id=debate.id,
            participant_id=debater.id,
            submitted_by_user_id=member.id,
            body="What about a different grid?",
            analysis_json='{"on_topic": false, "approved": false}',
            status="pending",
            created_at=NOW,
        )
    )
    db.commit()
    db.close()
    print("seeded")


if __name__ == "__main__":
    main()
