
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import (
    enforce_debate_manager,
    enforce_debate_participant_write,
    enforce_write_access,
    get_optional_user,
)
from app.core.clock import utcnow
from app.core.database import get_db
from app.models.argument import (
    ArgumentNode,
    ChallengeStatus,
    EvidenceChallenge,
    ModeratorRuling,
    Participant,
    ParticipantRole,
    RulingOutcome,
    VerificationStatus,
)
from app.models.auth import User, UserRole
from app.models.claim import Claim
from app.models.debate import Debate
from app.models.evidence import ClaimEvidence
from app.schemas.argument import (
    ArgumentNodeCreate,
    ArgumentNodeRead,
    EvidenceChallengeCreate,
    EvidenceChallengeRead,
    EvidenceChallengeUpdate,
    ModeratorRulingCreate,
    ModeratorRulingRead,
    ParticipantCreate,
    ParticipantRead,
    VerificationUpdate,
)

router = APIRouter(tags=["arguments"])


def require_debate(db: Session, debate_id: int) -> Debate:
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    return debate



def require_debate_manager(debate: Debate, user: User | None) -> None:
    enforce_write_access(user)
    if user and debate.owner_user_id and user.id != debate.owner_user_id and user.role not in {UserRole.moderator, UserRole.administrator}:
        raise HTTPException(status_code=403, detail="Only the debate owner or platform staff may manage this debate")


def require_participant(db: Session, participant_id: int, debate_id: int | None = None) -> Participant:
    participant = db.get(Participant, participant_id)
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    if debate_id is not None and participant.debate_id != debate_id:
        raise HTTPException(status_code=409, detail="Participant belongs to a different debate")
    return participant


@router.post("/debates/{debate_id}/participants", response_model=ParticipantRead, status_code=status.HTTP_201_CREATED)
def create_participant(
    debate_id: int,
    payload: ParticipantCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    debate = require_debate(db, debate_id)
    require_debate_manager(debate, user)
    participant = Participant(debate_id=debate_id, **payload.model_dump())
    db.add(participant)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This participant name is already used in the debate") from exc
    db.refresh(participant)
    return participant


@router.get("/debates/{debate_id}/participants", response_model=list[ParticipantRead])
def list_participants(debate_id: int, db: Session = Depends(get_db)):
    require_debate(db, debate_id)
    return db.query(Participant).filter(Participant.debate_id == debate_id).order_by(Participant.id).all()


@router.post("/debates/{debate_id}/arguments", response_model=ArgumentNodeRead, status_code=status.HTTP_201_CREATED)
def create_argument_node(
    debate_id: int,
    payload: ArgumentNodeCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    debate = require_debate(db, debate_id)
    participant = require_participant(db, payload.participant_id, debate_id)
    enforce_debate_participant_write(debate, user, participant)

    if payload.claim_id is not None:
        claim = db.get(Claim, payload.claim_id)
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")
        if claim.debate_id != debate_id:
            raise HTTPException(status_code=409, detail="Claim belongs to a different debate")

    if payload.parent_node_id is not None:
        parent = db.get(ArgumentNode, payload.parent_node_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent argument node not found")
        if parent.debate_id != debate_id:
            raise HTTPException(status_code=409, detail="Parent argument belongs to a different debate")

    node = ArgumentNode(
        debate_id=debate_id,
        side=participant.side,
        verification_status=VerificationStatus.unverified,
        **payload.model_dump(),
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@router.get("/debates/{debate_id}/arguments", response_model=list[ArgumentNodeRead])
def list_argument_nodes(debate_id: int, db: Session = Depends(get_db)):
    require_debate(db, debate_id)
    return db.query(ArgumentNode).filter(ArgumentNode.debate_id == debate_id).order_by(ArgumentNode.id).all()


@router.patch("/arguments/{argument_id}/verification", response_model=ArgumentNodeRead)
def update_verification(
    argument_id: int,
    payload: VerificationUpdate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    node = db.get(ArgumentNode, argument_id)
    if not node:
        raise HTTPException(status_code=404, detail="Argument node not found")
    debate = require_debate(db, node.debate_id)
    require_debate_manager(debate, user)
    if payload.verification_status in {VerificationStatus.verified, VerificationStatus.archived}:
        raise HTTPException(
            status_code=422,
            detail="verified and archived can only be set by a recorded verification event",
        )
    node.verification_status = payload.verification_status
    db.commit()
    db.refresh(node)
    return node


@router.post(
    "/claim-evidence/{claim_evidence_id}/challenges",
    response_model=EvidenceChallengeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_evidence_challenge(
    claim_evidence_id: int,
    payload: EvidenceChallengeCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    link = db.get(ClaimEvidence, claim_evidence_id)
    if not link:
        raise HTTPException(status_code=404, detail="Claim-evidence link not found")
    claim = db.get(Claim, link.claim_id)
    debate = require_debate(db, claim.debate_id)
    challenger = require_participant(db, payload.challenger_id, claim.debate_id)
    enforce_debate_participant_write(debate, user, challenger)
    challenge = EvidenceChallenge(
        claim_evidence_id=claim_evidence_id,
        challenger_id=challenger.id,
        reason=payload.reason,
        requested_remedy=payload.requested_remedy,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge


@router.patch("/challenges/{challenge_id}", response_model=EvidenceChallengeRead)
def update_evidence_challenge(
    challenge_id: int,
    payload: EvidenceChallengeUpdate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    challenge = db.get(EvidenceChallenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Evidence challenge not found")
    link = db.get(ClaimEvidence, challenge.claim_evidence_id)
    claim = db.get(Claim, link.claim_id)
    debate = require_debate(db, claim.debate_id)
    enforce_debate_manager(debate, user)
    challenge.status = payload.status
    challenge.response = payload.response
    if payload.status in {ChallengeStatus.upheld, ChallengeStatus.denied, ChallengeStatus.withdrawn}:
        challenge.resolved_at = utcnow()
    else:
        challenge.resolved_at = None
    db.commit()
    db.refresh(challenge)
    return challenge


@router.post("/debates/{debate_id}/rulings", response_model=ModeratorRulingRead, status_code=status.HTTP_201_CREATED)
def create_moderator_ruling(
    debate_id: int,
    payload: ModeratorRulingCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    debate = require_debate(db, debate_id)
    require_debate_manager(debate, user)
    moderator = require_participant(db, payload.moderator_id, debate_id)
    if moderator.role not in {ParticipantRole.moderator, ParticipantRole.ai_assistant}:
        raise HTTPException(status_code=403, detail="Only a moderator or AI assistant may issue rulings")

    node = None
    challenge = None
    if payload.argument_node_id is not None:
        node = db.get(ArgumentNode, payload.argument_node_id)
        if not node:
            raise HTTPException(status_code=404, detail="Argument node not found")
        if node.debate_id != debate_id:
            raise HTTPException(status_code=409, detail="Argument node belongs to a different debate")

    if payload.challenge_id is not None:
        challenge = db.get(EvidenceChallenge, payload.challenge_id)
        if not challenge:
            raise HTTPException(status_code=404, detail="Evidence challenge not found")
        link = db.get(ClaimEvidence, challenge.claim_evidence_id)
        claim = db.get(Claim, link.claim_id)
        if claim.debate_id != debate_id:
            raise HTTPException(status_code=409, detail="Challenge belongs to a different debate")

    ruling = ModeratorRuling(debate_id=debate_id, **payload.model_dump())
    db.add(ruling)

    if challenge is not None:
        if payload.outcome == RulingOutcome.challenge_upheld:
            challenge.status = ChallengeStatus.upheld
            challenge.resolved_at = utcnow()
        elif payload.outcome == RulingOutcome.challenge_denied:
            challenge.status = ChallengeStatus.denied
            challenge.resolved_at = utcnow()

    if node is not None:
        # Rulings are procedural. They do not verify or archive a claim.
        if payload.outcome in {RulingOutcome.excluded, RulingOutcome.challenge_upheld}:
            node.verification_status = VerificationStatus.rejected
        elif payload.outcome in {RulingOutcome.warning, RulingOutcome.revision_required}:
            node.verification_status = VerificationStatus.disputed

    db.commit()
    db.refresh(ruling)
    return ruling


@router.get("/debates/{debate_id}/rulings", response_model=list[ModeratorRulingRead])
def list_rulings(debate_id: int, db: Session = Depends(get_db)):
    require_debate(db, debate_id)
    return db.query(ModeratorRuling).filter(ModeratorRuling.debate_id == debate_id).order_by(ModeratorRuling.id).all()
