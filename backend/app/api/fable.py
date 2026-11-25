import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.authorization import get_optional_user, require_authenticated, require_role
from app.core.database import get_db
from app.models.auth import User, UserRole
from app.models.fable import (
    CHEATING_NOTICE,
    FableCanonNote,
    FableLoreItem,
    FableMatchup,
    FableMove,
    FableParticipant,
    FableRuling,
    FableReasoningStep,
    FableStepLore,
)
from app.schemas.fable import (
    FableCanonNoteCreate,
    FableCanonNoteRead,
    FableDebateOutcome,
    FableLoreCreate,
    FableLoreRead,
    FableMatchupCreate,
    FableMatchupRead,
    FableMoveCreate,
    FableMoveRead,
    FableParticipantRead,
    FableRulingRead,
    FableRulingCreate,
    FableStepCreate,
    FableStepRead,
)
from app.schemas.fable import (
    FableSettings,
    FableOverride,
)
from app.services.referee import accept_ruling, evidence_flags, override_ruling, rule_submitted_moves
from app.services.fable import (
    REFEREE_SCOPE,
    FableError,
    add_canon_note,
    add_lore,
    add_move,
    add_step,
    automated_run,
    create_matchup,
    record_debate_outcome,
    rule_move,
)

router = APIRouter(prefix="/fable", tags=["epic-fable"])


def _guard(action):
    try:
        return action()
    except FableError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _require(db: Session, matchup_id: int) -> FableMatchup:
    matchup = db.get(FableMatchup, matchup_id)
    if matchup is None:
        raise HTTPException(status_code=404, detail="Fable matchup not found")
    return matchup


def _read(db: Session, matchup: FableMatchup) -> FableMatchupRead:
    participants = db.query(FableParticipant).filter(FableParticipant.matchup_id == matchup.id).order_by(FableParticipant.id).all()
    lore = db.query(FableLoreItem).filter(FableLoreItem.matchup_id == matchup.id).order_by(FableLoreItem.id).all()
    steps = db.query(FableReasoningStep).filter(FableReasoningStep.matchup_id == matchup.id).order_by(FableReasoningStep.step_number).all()
    notes = db.query(FableCanonNote).filter(FableCanonNote.matchup_id == matchup.id).order_by(FableCanonNote.id).all()
    moves = db.query(FableMove).filter(FableMove.matchup_id == matchup.id).order_by(FableMove.id).all()
    step_reads = []
    for step in steps:
        lore_ids = [row[0] for row in db.query(FableStepLore.lore_item_id).filter(FableStepLore.step_id == step.id).all()]
        step_reads.append(FableStepRead(id=step.id, step_number=step.step_number, body=step.body, lore_item_ids=lore_ids))
    try:
        move_ids = json.loads(matchup.debate_outcome_move_ids) if matchup.debate_outcome_move_ids else []
    except json.JSONDecodeError:
        move_ids = []
    return FableMatchupRead(
        id=matchup.id,
        title=matchup.title,
        question=matchup.question,
        mode=matchup.mode,
        personal_knowledge_only=matchup.personal_knowledge_only,
        referee_mode=matchup.referee_mode,
        canon_only=matchup.canon_only,
        participants=[FableParticipantRead(id=row.id, name=row.name) for row in participants],
        lore=[FableLoreRead.model_validate(row) for row in lore],
        steps=step_reads,
        canon_notes=[FableCanonNoteRead.model_validate(row) for row in notes],
        moves=[_move_read(db, row) for row in moves],
        ai_outcome=matchup.ai_outcome,
        ai_outcome_note=matchup.ai_outcome_note,
        debate_outcome=matchup.debate_outcome,
        debate_outcome_note=matchup.debate_outcome_note,
        debate_outcome_move_ids=move_ids,
        automated_analysis=matchup.automated_analysis,
        automated_referee=matchup.automated_referee,
        referee_scope=REFEREE_SCOPE,
        cheating_notice=CHEATING_NOTICE,
        created_at=matchup.created_at,
    )


@router.post("/matchups", response_model=FableMatchupRead, status_code=status.HTTP_201_CREATED)
def post_matchup(payload: FableMatchupCreate, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    matchup = _guard(lambda: create_matchup(db, user.id if user else None, payload))
    db.commit()
    return _read(db, matchup)


@router.get("/matchups", response_model=list[FableMatchupRead])
def list_matchups(db: Session = Depends(get_db)):
    return [_read(db, row) for row in db.query(FableMatchup).order_by(FableMatchup.id).all()]


@router.get("/matchups/{matchup_id}", response_model=FableMatchupRead)
def get_matchup(matchup_id: int, db: Session = Depends(get_db)):
    return _read(db, _require(db, matchup_id))


@router.post("/matchups/{matchup_id}/lore", response_model=FableLoreRead, status_code=201)
def post_lore(matchup_id: int, payload: FableLoreCreate, db: Session = Depends(get_db), _: User | None = Depends(get_optional_user)):
    item = _guard(lambda: add_lore(db, _require(db, matchup_id), payload))
    db.commit()
    return item


@router.post("/matchups/{matchup_id}/steps", response_model=FableStepRead, status_code=201)
def post_step(matchup_id: int, payload: FableStepCreate, db: Session = Depends(get_db), _: User | None = Depends(get_optional_user)):
    step = _guard(lambda: add_step(db, _require(db, matchup_id), payload))
    db.commit()
    lore_ids = [row[0] for row in db.query(FableStepLore.lore_item_id).filter(FableStepLore.step_id == step.id).all()]
    return FableStepRead(id=step.id, step_number=step.step_number, body=step.body, lore_item_ids=lore_ids)


@router.post("/matchups/{matchup_id}/canon-notes", response_model=FableCanonNoteRead, status_code=201)
def post_note(matchup_id: int, payload: FableCanonNoteCreate, db: Session = Depends(get_db), _: User | None = Depends(get_optional_user)):
    note = _guard(lambda: add_canon_note(db, _require(db, matchup_id), payload))
    db.commit()
    return note


@router.post("/matchups/{matchup_id}/moves", response_model=FableMoveRead, status_code=201)
def post_move(matchup_id: int, payload: FableMoveCreate, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    matchup = _require(db, matchup_id)
    move = _guard(lambda: add_move(db, matchup, payload))
    if matchup.mode == "debate" and matchup.referee_mode != "moderator_only":
        rule_submitted_moves(db, matchup, user.id if user else None)
    db.commit()
    db.refresh(move)
    return move


@router.post("/moves/{move_id}/ruling", response_model=FableMoveRead)
def post_ruling(
    move_id: int,
    payload: FableRulingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    move = db.get(FableMove, move_id)
    if move is None:
        raise HTTPException(status_code=404, detail="Move not found")
    _guard(lambda: rule_move(db, move, user.id, payload))
    db.add(FableRuling(
        move_id=move.id,
        ruling=move.ruling,
        reason=move.reason,
        citation=move.citation,
        lore_item_ids="[]",
        confidence=None,
        ruled_by="moderator",
        status="accepted",
        created_by_user_id=user.id,
    ))
    db.commit()
    db.refresh(move)
    return move


@router.post("/matchups/{matchup_id}/debate-outcome", response_model=FableMatchupRead)
def post_debate_outcome(
    matchup_id: int,
    payload: FableDebateOutcome,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    del user
    matchup = _require(db, matchup_id)
    _guard(lambda: record_debate_outcome(db, matchup, payload))
    db.commit()
    return _read(db, matchup)


@router.post("/matchups/{matchup_id}/automated-run")
def post_automated_run(matchup_id: int, db: Session = Depends(get_db), _: User | None = Depends(get_optional_user)):
    matchup = _require(db, matchup_id)
    result = _guard(lambda: automated_run(matchup))
    db.commit()
    stored = db.get(FableMatchup, matchup_id)
    if stored.ai_outcome is not None or stored.debate_outcome is not None:
        raise HTTPException(status_code=409, detail="An unimplemented AI run must not write an outcome.")
    return result


@router.post("/matchups/{matchup_id}/automated-referee")
def post_automated_referee(
    matchup_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    matchup = _require(db, matchup_id)
    before_ids = [row.id for row in db.query(FableMove).filter(FableMove.matchup_id == matchup.id).all()]
    rulings = rule_submitted_moves(db, matchup, user.id)
    db.commit()
    after_ids = [row.id for row in db.query(FableMove).filter(FableMove.matchup_id == matchup.id).all()]
    if after_ids != before_ids:
        raise HTTPException(status_code=409, detail="The referee must not introduce a move.")
    return {
        "provider": rulings[0].provider_name if rulings else "deterministic-lore",
        "rulings_recorded": len(rulings),
        "moves_added": 0,
        "detail": "The referee ruled only submitted moves. It did not introduce a counter.",
    }


@router.get("/referee/queue")
def referee_queue(db: Session = Depends(get_db), _: User = Depends(require_role(UserRole.moderator, UserRole.administrator))):
    rows = db.query(FableRuling).filter(FableRuling.status == "proposed").order_by(FableRuling.id).all()
    return [_ruling_dict(row) for row in rows]


@router.post("/rulings/{ruling_id}/accept")
def accept(ruling_id: int, db: Session = Depends(get_db), _: User = Depends(require_role(UserRole.moderator, UserRole.administrator))):
    ruling = db.get(FableRuling, ruling_id)
    move = db.get(FableMove, ruling.move_id) if ruling else None
    if ruling is None or move is None:
        raise HTTPException(status_code=404, detail="Ruling not found")
    accept_ruling(ruling, move)
    db.commit()
    return _ruling_dict(ruling)


@router.post("/rulings/{ruling_id}/override")
def override(
    ruling_id: int,
    payload: FableOverride,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.moderator, UserRole.administrator)),
):
    ruling = db.get(FableRuling, ruling_id)
    move = db.get(FableMove, ruling.move_id) if ruling else None
    if ruling is None or move is None:
        raise HTTPException(status_code=404, detail="Ruling not found")
    before = db.query(FableMove).filter(FableMove.matchup_id == move.matchup_id).count()
    replacement = override_ruling(db, ruling, move, user.id, payload)
    db.commit()
    after = db.query(FableMove).filter(FableMove.matchup_id == move.matchup_id).count()
    if after != before:
        raise HTTPException(status_code=409, detail="An override cannot introduce a move.")
    history = db.query(FableRuling).filter(FableRuling.move_id == move.id).order_by(FableRuling.id).all()
    return {"current": _ruling_dict(replacement), "history": [_ruling_dict(row) for row in history]}


@router.post("/rulings/{ruling_id}/recheck")
def recheck(ruling_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.moderator, UserRole.administrator))):
    ruling = db.get(FableRuling, ruling_id)
    if ruling is None:
        raise HTTPException(status_code=404, detail="Ruling not found")
    move = db.get(FableMove, ruling.move_id)
    matchup = db.get(FableMatchup, move.matchup_id)
    move.ruling = None
    created = rule_submitted_moves(db, matchup, user.id)
    db.commit()
    return {"rulings": [_ruling_dict(row) for row in created]}


@router.patch("/matchups/{matchup_id}/settings", response_model=FableMatchupRead)
def patch_settings(matchup_id: int, payload: FableSettings, db: Session = Depends(get_db), _: User = Depends(require_role(UserRole.moderator, UserRole.administrator))):
    matchup = _require(db, matchup_id)
    matchup.referee_mode = payload.referee_mode
    matchup.canon_only = payload.canon_only
    matchup.personal_knowledge_only = payload.personal_knowledge_only
    db.commit()
    return _read(db, matchup)


def _move_read(db: Session, move: FableMove) -> FableMoveRead:
    history = db.query(FableRuling).filter(FableRuling.move_id == move.id).order_by(FableRuling.id).all()
    payload = FableMoveRead.model_validate(move)
    payload.rulings = [
        FableRulingRead(
            id=row.id,
            ruling=row.ruling,
            reason=row.reason,
            citation=row.citation,
            lore_item_ids=json.loads(row.lore_item_ids or "[]"),
            confidence=row.confidence,
            ruled_by=row.ruled_by,
            provider_name=row.provider_name,
            provider_version=row.provider_version,
            status=row.status,
            override_reason=row.override_reason,
        )
        for row in history
    ]
    return payload


def _ruling_dict(row: FableRuling) -> dict:
    return {
        "id": row.id,
        "move_id": row.move_id,
        "ruling": row.ruling,
        "reason": row.reason,
        "citation": row.citation,
        "lore_item_ids": json.loads(row.lore_item_ids or "[]"),
        "confidence": row.confidence,
        "ruled_by": row.ruled_by,
        "provider_name": row.provider_name,
        "provider_version": row.provider_version,
        "status": row.status,
        "override_reason": row.override_reason,
    }
