"""Fiction matchups. Lore is not factual evidence.

AI matchup runs and AI refereeing are not implemented. A debate outcome is
stored apart from an AI matchup outcome. The referee records a ruling only on
a move a debater already submitted and does not add a counter.
"""
import json

from sqlalchemy.orm import Session

from app.models.fable import (
    AUTOMATED_FABLE,
    FableCanonNote,
    FableLoreItem,
    FableMatchup,
    FableMove,
    FableParticipant,
    FableReasoningStep,
    FableStepLore,
)

AI_RUN_DETAIL = (
    "An AI matchup run is not implemented. No outcome was generated, "
    "and no debate outcome was changed."
)
AI_REFEREE_DETAIL = (
    "Automated AI refereeing is not implemented. No move was ruled, "
    "and no counter, power, or fact was introduced."
)
DEBATE_NO_HELP = (
    "Debate mode does not ask the AI for help. The referee rules only on moves "
    "a debater already made and does not coach, suggest powers, or answer questions."
)
REFEREE_SCOPE = (
    "The referee rules only on moves actually made. It does not introduce counters, "
    "powers, or facts a debater did not raise. The debate outcome uses only those moves "
    "and their rulings, so a side that does not raise a valid canon counter can lose."
)


class FableError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def create_matchup(db: Session, user_id: int | None, payload) -> FableMatchup:
    names = [name.strip() for name in payload.participants if name.strip()]
    if payload.mode == "ai_matchup" and len(names) != 2:
        raise FableError(422, "An AI matchup is two characters.")
    if len(names) < 2:
        raise FableError(422, "A matchup needs at least two participants.")
    matchup = FableMatchup(
        title=payload.title.strip(),
        question=payload.question.strip(),
        mode=payload.mode,
        personal_knowledge_only=True if payload.mode == "debate" else bool(payload.personal_knowledge_only),
        automated_analysis=AUTOMATED_FABLE,
        automated_referee=AUTOMATED_FABLE,
        created_by_user_id=user_id,
    )
    db.add(matchup)
    db.flush()
    for name in names:
        db.add(FableParticipant(matchup_id=matchup.id, name=name))
    db.flush()
    return matchup


def add_lore(db: Session, matchup: FableMatchup, payload) -> FableLoreItem:
    item = FableLoreItem(matchup_id=matchup.id, **payload.model_dump())
    db.add(item)
    db.flush()
    return item


def add_step(db: Session, matchup: FableMatchup, payload) -> FableReasoningStep:
    lore_ids = set(payload.lore_item_ids)
    owned = {
        row[0]
        for row in db.query(FableLoreItem.id).filter(
            FableLoreItem.matchup_id == matchup.id, FableLoreItem.id.in_(lore_ids)
        ).all()
    }
    if owned != lore_ids:
        raise FableError(422, "A reasoning step can cite only lore items recorded on this matchup.")
    step = FableReasoningStep(matchup_id=matchup.id, step_number=payload.step_number, body=payload.body.strip())
    db.add(step)
    db.flush()
    for lore_id in lore_ids:
        db.add(FableStepLore(step_id=step.id, lore_item_id=lore_id))
    return step


def add_canon_note(db: Session, matchup: FableMatchup, payload) -> FableCanonNote:
    note = FableCanonNote(matchup_id=matchup.id, kind=payload.kind, note=payload.note.strip())
    db.add(note)
    db.flush()
    return note


def add_move(db: Session, matchup: FableMatchup, payload) -> FableMove:
    if matchup.mode != "debate":
        raise FableError(409, "Moves are recorded only in a personal-knowledge debate.")
    participant = db.get(FableParticipant, payload.participant_id)
    if participant is None or participant.matchup_id != matchup.id:
        raise FableError(404, "Participant not found on this matchup.")
    if payload.lore_item_id is not None:
        lore = db.get(FableLoreItem, payload.lore_item_id)
        if lore is None or lore.matchup_id != matchup.id:
            raise FableError(422, "The canon citation must be a lore item on this matchup.")
    move = FableMove(
        matchup_id=matchup.id,
        participant_id=payload.participant_id,
        move_text=payload.move_text.strip(),
        claimed_source=payload.claimed_source.strip(),
        lore_item_id=payload.lore_item_id,
    )
    db.add(move)
    db.flush()
    return move


def rule_move(db: Session, move: FableMove, user_id: int, payload) -> FableMove:
    count_before = db.query(FableMove.id).filter(FableMove.matchup_id == move.matchup_id).count()
    move.ruling = payload.ruling
    move.reason = payload.reason.strip()
    move.citation = payload.citation.strip()
    move.ruled_by = "moderator"
    move.ruled_by_user_id = user_id
    count_after = db.query(FableMove.id).filter(FableMove.matchup_id == move.matchup_id).count()
    if count_after != count_before:
        raise FableError(409, "A ruling cannot introduce a move the debater did not make.")
    return move


def record_debate_outcome(db: Session, matchup: FableMatchup, payload) -> FableMatchup:
    if matchup.mode != "debate":
        raise FableError(409, "A debate outcome cannot be stored on an AI matchup, and it cannot overwrite an AI outcome.")
    ai_before = (matchup.ai_outcome, matchup.ai_outcome_note)
    moves = {move.id: move for move in db.query(FableMove).filter(FableMove.matchup_id == matchup.id).all()}
    if any(move_id not in moves for move_id in payload.move_ids):
        raise FableError(422, "A debate outcome can use only moves that were actually made.")
    if any(not moves[move_id].ruling for move_id in payload.move_ids):
        raise FableError(422, "A debate outcome can use only moves that have a referee ruling.")
    matchup.debate_outcome = payload.outcome.strip()
    matchup.debate_outcome_note = payload.note.strip()
    matchup.debate_outcome_move_ids = json.dumps(list(payload.move_ids))
    if (matchup.ai_outcome, matchup.ai_outcome_note) != ai_before:
        raise FableError(409, "Recording a debate outcome changed the AI matchup outcome.")
    return matchup


def automated_run(matchup: FableMatchup) -> dict:
    if matchup.mode != "ai_matchup":
        raise FableError(409, DEBATE_NO_HELP)
    return {
        "automated_analysis": AUTOMATED_FABLE,
        "detail": AI_RUN_DETAIL,
        "ai_outcome": matchup.ai_outcome,
        "debate_outcome": matchup.debate_outcome,
    }


def automated_referee(matchup: FableMatchup) -> dict:
    return {
        "automated_referee": AUTOMATED_FABLE,
        "detail": AI_REFEREE_DETAIL,
        "personal_knowledge_only": matchup.personal_knowledge_only,
    }
