import asyncio
import json
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import get_optional_user, require_authenticated
from app.core.database import SessionLocal, get_db
from app.core.security import token_digest
from app.models.argument import Participant
from app.models.auth import AuthSession, User, UserRole
from app.models.collaboration import DebateEvent, DebateInvitation, InvitationStatus, DebateTurn, DebateRoomState, TurnStatus, TurnModerationReview, ModerationReviewStatus
from app.models.debate import Debate
from app.schemas.argument import ParticipantRead
from app.schemas.collaboration import DebateEventRead, InvitationAccept, InvitationCreate, InvitationRead, TurnCreate, TurnRead, RoomStateRead, RoomConfigure, TurnPreview, TurnAnalysisRead, ModerationReviewRead, ModerationDecision
from app.services.realtime import event_dict, manager, record_event
from app.services.turn_moderation import analyze_turn
from app.core.clock import utcnow

router = APIRouter(tags=["collaboration"])


def require_manager(debate: Debate, user: User):
    if debate.owner_user_id != user.id and user.role not in {UserRole.moderator, UserRole.administrator}:
        raise HTTPException(403, "Only the debate owner or platform staff may manage invitations")


@router.post("/debates/{debate_id}/invitations", response_model=InvitationRead, status_code=status.HTTP_201_CREATED)
def create_invitation(
    debate_id: int,
    payload: InvitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated),
):
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(404, "Debate not found")
    require_manager(debate, user)
    raw_token = secrets.token_urlsafe(32)
    invite = DebateInvitation(
        debate_id=debate_id,
        created_by_user_id=user.id,
        token_hash=token_digest(raw_token),
        invited_email=str(payload.invited_email).lower() if payload.invited_email else None,
        participant_role=payload.participant_role.value,
        side=payload.side.value,
        max_uses=payload.max_uses,
        expires_at=utcnow() + timedelta(hours=payload.expires_in_hours),
    )
    db.add(invite)
    db.commit(); db.refresh(invite)
    data = InvitationRead.model_validate(invite).model_copy(update={"invite_token": raw_token})
    return data


@router.get("/debates/{debate_id}/invitations", response_model=list[InvitationRead])
def list_invitations(debate_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(404, "Debate not found")
    require_manager(debate, user)
    return db.query(DebateInvitation).filter(DebateInvitation.debate_id == debate_id).order_by(DebateInvitation.id.desc()).all()


@router.post("/invitations/accept", response_model=ParticipantRead)
def accept_invitation(payload: InvitationAccept, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    invite = db.query(DebateInvitation).filter(DebateInvitation.token_hash == token_digest(payload.token)).first()
    if not invite:
        raise HTTPException(404, "Invitation not found")
    if invite.status != InvitationStatus.pending or invite.expires_at <= utcnow():
        raise HTTPException(410, "Invitation is no longer valid")
    if invite.invited_email and invite.invited_email != user.email.lower():
        raise HTTPException(403, "This invitation was issued to a different email address")
    existing = db.query(Participant).filter(Participant.debate_id == invite.debate_id, Participant.user_id == user.id).first()
    if existing:
        return existing
    participant = Participant(
        debate_id=invite.debate_id,
        user_id=user.id,
        display_name=payload.display_name,
        role=invite.participant_role,
        side=invite.side,
    )
    db.add(participant)
    invite.use_count += 1
    if invite.use_count >= invite.max_uses:
        invite.status = InvitationStatus.accepted
    try:
        event = record_event(db, invite.debate_id, "participant.joined", {"display_name": payload.display_name, "participant_id": None}, user.id)
        db.commit(); db.refresh(participant)
        event.payload_json = json.dumps({"display_name": participant.display_name, "participant_id": participant.id})
        db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "That display name is already in use") from exc
    return participant


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    invite = db.get(DebateInvitation, invitation_id)
    if not invite:
        raise HTTPException(404, "Invitation not found")
    debate = db.get(Debate, invite.debate_id); require_manager(debate, user)
    invite.status = InvitationStatus.revoked
    db.commit()


@router.get("/debates/{debate_id}/events", response_model=list[DebateEventRead])
def list_events(debate_id: int, after_id: int = 0, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    if not db.get(Debate, debate_id):
        raise HTTPException(404, "Debate not found")
    rows = db.query(DebateEvent).filter(DebateEvent.debate_id == debate_id, DebateEvent.id > after_id).order_by(DebateEvent.id).limit(limit).all()
    return [DebateEventRead(**event_dict(row)) for row in rows]


def websocket_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = db.query(AuthSession).filter(AuthSession.token_hash == token_digest(token)).first()
    if not session or session.expires_at <= utcnow():
        return None
    return db.get(User, session.user_id)


@router.websocket("/ws/debates/{debate_id}")
async def debate_socket(websocket: WebSocket, debate_id: int, token: str | None = Query(default=None)):
    db = SessionLocal()
    try:
        debate = db.get(Debate, debate_id)
        user = websocket_user(db, token)
        if not debate or not user:
            await websocket.close(code=4401)
            return
        participant = db.query(Participant).filter(Participant.debate_id == debate_id, Participant.user_id == user.id).first()
        if debate.owner_user_id != user.id and not participant and user.role not in {UserRole.moderator, UserRole.administrator}:
            await websocket.close(code=4403)
            return
        await manager.connect(debate_id, websocket)
        await websocket.send_json({"event_type": "room.connected", "debate_id": debate_id})
        last_event_id = 0
        while True:
            db.expire_all()
            events = db.query(DebateEvent).filter(DebateEvent.debate_id == debate_id, DebateEvent.id > last_event_id).order_by(DebateEvent.id).limit(100).all()
            for event in events:
                await websocket.send_json(event_dict(event))
                last_event_id = event.id
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        await manager.disconnect(debate_id, websocket)
    finally:
        db.close()


def room_participants(db: Session, debate_id: int):
    return db.query(Participant).filter(
        Participant.debate_id == debate_id,
        Participant.role == "debater",
    ).order_by(Participant.id).all()


def ensure_room_access(db: Session, debate: Debate, user: User) -> Participant | None:
    participant = db.query(Participant).filter(Participant.debate_id == debate.id, Participant.user_id == user.id).first()
    if debate.owner_user_id != user.id and not participant and user.role not in {UserRole.moderator, UserRole.administrator}:
        raise HTTPException(403, "You do not have access to this debate room")
    return participant


def state_payload(state: DebateRoomState) -> dict:
    remaining = None
    if state.current_participant_id and state.turn_started_at:
        elapsed = (utcnow() - state.turn_started_at).total_seconds()
        remaining = max(0, state.turn_duration_seconds - int(elapsed))
    return {
        "debate_id": state.debate_id,
        "current_participant_id": state.current_participant_id,
        "turn_duration_seconds": state.turn_duration_seconds,
        "turn_started_at": state.turn_started_at,
        "turn_sequence": state.turn_sequence,
        "remaining_seconds": remaining,
    }


def advance_state(db: Session, state: DebateRoomState):
    participants = room_participants(db, state.debate_id)
    if not participants:
        state.current_participant_id = None
        state.turn_started_at = None
        return
    ids = [p.id for p in participants]
    if state.current_participant_id not in ids:
        next_id = ids[0]
    else:
        next_id = ids[(ids.index(state.current_participant_id) + 1) % len(ids)]
    state.current_participant_id = next_id
    state.turn_sequence += 1
    state.turn_started_at = utcnow()


@router.put("/debates/{debate_id}/room", response_model=RoomStateRead)
def configure_room(debate_id: int, payload: RoomConfigure, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    debate = db.get(Debate, debate_id)
    if not debate:
        raise HTTPException(404, "Debate not found")
    require_manager(debate, user)
    participants = room_participants(db, debate_id)
    if payload.first_participant_id and payload.first_participant_id not in {p.id for p in participants}:
        raise HTTPException(400, "First participant must be a debater in this room")
    state = db.get(DebateRoomState, debate_id) or DebateRoomState(debate_id=debate_id)
    state.turn_duration_seconds = payload.turn_duration_seconds
    state.current_participant_id = payload.first_participant_id or (participants[0].id if participants else None)
    state.turn_started_at = utcnow() if state.current_participant_id else None
    if not db.get(DebateRoomState, debate_id): db.add(state)
    event = record_event(db, debate_id, "room.configured", state_payload(state), user.id)
    db.commit(); db.refresh(state)
    return RoomStateRead(**state_payload(state))


@router.get("/debates/{debate_id}/room", response_model=RoomStateRead)
def get_room(debate_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    debate = db.get(Debate, debate_id)
    if not debate: raise HTTPException(404, "Debate not found")
    ensure_room_access(db, debate, user)
    state = db.get(DebateRoomState, debate_id)
    if not state:
        state = DebateRoomState(debate_id=debate_id)
        db.add(state); db.commit(); db.refresh(state)
    return RoomStateRead(**state_payload(state))


@router.get("/debates/{debate_id}/turns", response_model=list[TurnRead])
def list_turns(debate_id: int, after_id: int = 0, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    debate = db.get(Debate, debate_id)
    if not debate: raise HTTPException(404, "Debate not found")
    ensure_room_access(db, debate, user)
    return db.query(DebateTurn).filter(DebateTurn.debate_id == debate_id, DebateTurn.id > after_id).order_by(DebateTurn.sequence_number).limit(limit).all()


@router.post("/debates/{debate_id}/turns/preview", response_model=TurnAnalysisRead)
def preview_turn(debate_id: int, payload: TurnPreview, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    debate = db.get(Debate, debate_id)
    if not debate: raise HTTPException(404, "Debate not found")
    ensure_room_access(db, debate, user)
    if payload.rebuttal_target_turn_id:
        target = db.get(DebateTurn, payload.rebuttal_target_turn_id)
        if not target or target.debate_id != debate_id:
            raise HTTPException(400, "Rebuttal target must be a turn in this debate")
    return TurnAnalysisRead(**analyze_turn(debate.fixed_question, payload.body, payload.rebuttal_target_turn_id).to_dict())


def review_dict(row: TurnModerationReview) -> dict:
    return {
        "id": row.id, "debate_id": row.debate_id, "participant_id": row.participant_id,
        "submitted_by_user_id": row.submitted_by_user_id, "body": row.body,
        "rebuttal_target_turn_id": row.rebuttal_target_turn_id, "analysis": json.loads(row.analysis_json),
        "status": row.status.value if hasattr(row.status, "value") else row.status,
        "moderator_user_id": row.moderator_user_id, "moderator_note": row.moderator_note,
        "created_at": row.created_at, "resolved_at": row.resolved_at,
    }


@router.get("/debates/{debate_id}/moderation-reviews", response_model=list[ModerationReviewRead])
def list_moderation_reviews(debate_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    debate = db.get(Debate, debate_id)
    if not debate: raise HTTPException(404, "Debate not found")
    require_manager(debate, user)
    rows = db.query(TurnModerationReview).filter(TurnModerationReview.debate_id == debate_id).order_by(TurnModerationReview.id.desc()).all()
    return [ModerationReviewRead(**review_dict(row)) for row in rows]


@router.post("/moderation-reviews/{review_id}/decision", response_model=ModerationReviewRead)
def decide_moderation_review(review_id: int, payload: ModerationDecision, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    review = db.get(TurnModerationReview, review_id)
    if not review: raise HTTPException(404, "Moderation review not found")
    debate = db.get(Debate, review.debate_id); require_manager(debate, user)
    if review.status != ModerationReviewStatus.pending: raise HTTPException(409, "Review has already been resolved")
    review.status = ModerationReviewStatus.approved if payload.approve else ModerationReviewStatus.rejected
    review.moderator_user_id = user.id; review.moderator_note = payload.note; review.resolved_at = utcnow()
    if payload.approve:
        state = db.get(DebateRoomState, review.debate_id)
        if not state or state.current_participant_id != review.participant_id:
            raise HTTPException(409, "The participant is no longer the current speaker")
        now = utcnow()
        turn = DebateTurn(debate_id=review.debate_id, participant_id=review.participant_id, sequence_number=state.turn_sequence, body=review.body, status=TurnStatus.completed, started_at=state.turn_started_at or now, submitted_at=now)
        db.add(turn); db.flush()
        record_event(db, review.debate_id, "turn.moderator_approved", {"turn_id": turn.id, "review_id": review.id, "participant_id": review.participant_id}, user.id)
        advance_state(db, state)
    else:
        record_event(db, review.debate_id, "turn.moderator_rejected", {"review_id": review.id, "participant_id": review.participant_id}, user.id)
    db.commit(); db.refresh(review)
    return ModerationReviewRead(**review_dict(review))


@router.post("/debates/{debate_id}/turns", response_model=TurnRead, status_code=201)
def submit_turn(debate_id: int, payload: TurnCreate, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    debate = db.get(Debate, debate_id)
    if not debate: raise HTTPException(404, "Debate not found")
    participant = ensure_room_access(db, debate, user)
    if not participant or participant.role.value != "debater":
        raise HTTPException(403, "Only a debater may submit a turn")
    state = db.get(DebateRoomState, debate_id)
    if not state or not state.current_participant_id:
        raise HTTPException(409, "The debate room has not been started")
    if state.current_participant_id != participant.id:
        raise HTTPException(409, "It is not your turn")
    now = utcnow()
    if state.turn_started_at and (now - state.turn_started_at).total_seconds() > state.turn_duration_seconds:
        expired = DebateTurn(debate_id=debate_id, participant_id=participant.id, sequence_number=state.turn_sequence, body="", status=TurnStatus.expired, started_at=state.turn_started_at, submitted_at=now)
        db.add(expired); advance_state(db, state); record_event(db, debate_id, "turn.expired", {"participant_id": participant.id, "sequence_number": expired.sequence_number}, user.id); db.commit()
        raise HTTPException(409, "Your turn expired and the room advanced")
    if payload.rebuttal_target_turn_id:
        target = db.get(DebateTurn, payload.rebuttal_target_turn_id)
        if not target or target.debate_id != debate_id:
            raise HTTPException(400, "Rebuttal target must be a turn in this debate")
    analysis = analyze_turn(debate.fixed_question, payload.body, payload.rebuttal_target_turn_id)
    if not analysis.approved:
        review = TurnModerationReview(debate_id=debate_id, participant_id=participant.id, submitted_by_user_id=user.id, body=payload.body.strip(), rebuttal_target_turn_id=payload.rebuttal_target_turn_id, analysis_json=json.dumps(analysis.to_dict()))
        db.add(review); db.flush()
        record_event(db, debate_id, "turn.flagged", {"review_id": review.id, "participant_id": participant.id, "reasons": analysis.reasons}, user.id)
        db.commit()
        raise HTTPException(422, {"message": "Turn requires moderator review", "review_id": review.id, "analysis": analysis.to_dict()})
    turn = DebateTurn(debate_id=debate_id, participant_id=participant.id, sequence_number=state.turn_sequence, body=payload.body.strip(), status=TurnStatus.completed, started_at=state.turn_started_at or now, submitted_at=now)
    db.add(turn); db.flush()
    record_event(db, debate_id, "turn.submitted", {"turn_id": turn.id, "participant_id": participant.id, "sequence_number": turn.sequence_number, "body": turn.body}, user.id)
    advance_state(db, state)
    record_event(db, debate_id, "turn.advanced", {"current_participant_id": state.current_participant_id, "turn_sequence": state.turn_sequence}, user.id)
    db.commit(); db.refresh(turn)
    return turn


@router.post("/debates/{debate_id}/turns/skip", response_model=RoomStateRead)
def skip_turn(debate_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated)):
    debate = db.get(Debate, debate_id)
    if not debate: raise HTTPException(404, "Debate not found")
    require_manager(debate, user)
    state = db.get(DebateRoomState, debate_id)
    if not state or not state.current_participant_id: raise HTTPException(409, "The debate room has not been started")
    skipped_id = state.current_participant_id
    db.add(DebateTurn(debate_id=debate_id, participant_id=skipped_id, sequence_number=state.turn_sequence, body="", status=TurnStatus.skipped, started_at=state.turn_started_at or utcnow(), submitted_at=utcnow()))
    advance_state(db, state)
    record_event(db, debate_id, "turn.skipped", {"participant_id": skipped_id, "current_participant_id": state.current_participant_id, "turn_sequence": state.turn_sequence}, user.id)
    db.commit(); db.refresh(state)
    return RoomStateRead(**state_payload(state))
