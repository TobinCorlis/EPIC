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
    FableRulingCreate,
    FableStepCreate,
    FableStepRead,
)
from app.services.fable import (
    REFEREE_SCOPE,
    FableError,
    add_canon_note,
    add_lore,
    add_move,
    add_step,
    automated_referee,
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
        participants=[FableParticipantRead(id=row.id, name=row.name) for row in participants],
        lore=[FableLoreRead.model_validate(row) for row in lore],
        steps=step_reads,
        canon_notes=[FableCanonNoteRead.model_validate(row) for row in notes],
        moves=[FableMoveRead.model_validate(row) for row in moves],
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
def post_move(matchup_id: int, payload: FableMoveCreate, db: Session = Depends(get_db), _: User | None = Depends(get_optional_user)):
    move = _guard(lambda: add_move(db, _require(db, matchup_id), payload))
    db.commit()
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
def post_automated_referee(matchup_id: int, db: Session = Depends(get_db), _: User = Depends(require_authenticated)):
    matchup = _require(db, matchup_id)
    before = [(row.id, row.ruling, row.move_text) for row in db.query(FableMove).filter(FableMove.matchup_id == matchup.id).all()]
    result = automated_referee(matchup)
    db.commit()
    after = [(row.id, row.ruling, row.move_text) for row in db.query(FableMove).filter(FableMove.matchup_id == matchup.id).all()]
    if after != before:
        raise HTTPException(status_code=409, detail="Automated refereeing must not add or change a move.")
    return result
