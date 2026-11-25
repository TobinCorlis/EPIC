"""Create clearly labeled DEMO FABLE matchups.

Run from the repository root:

    cd backend && PYTHONPATH=. python3 ../scripts/seed_fable_demo.py

Running it again does not add a second copy. The matchups are fiction, not evidence.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionLocal
from app.models.fable import FableLoreItem, FableMatchup, FableMove, FableParticipant, FableRuling
from app.services.referee import rule_submitted_moves

AUTO_TITLE = "DEMO: Lantern vs Comet"
SUGGEST_TITLE = "DEMO: Lantern vs Comet (suggest)"


def _existing(db, title: str) -> FableMatchup | None:
    return db.query(FableMatchup).filter(FableMatchup.title == title).one_or_none()


def _auto_matchup(db) -> FableMatchup:
    found = _existing(db, AUTO_TITLE)
    if found is not None:
        return found
    matchup = FableMatchup(
        title=AUTO_TITLE,
        question="DEMO fiction only. Who lands the recorded blow?",
        mode="debate",
        personal_knowledge_only=True,
        referee_mode="ai_auto",
        canon_only=True,
        automated_analysis="not_implemented",
        automated_referee="deterministic-lore",
    )
    db.add(matchup)
    db.flush()
    lantern = FableParticipant(matchup_id=matchup.id, name="Lantern")
    comet = FableParticipant(matchup_id=matchup.id, name="Comet")
    db.add_all([lantern, comet])
    db.flush()
    lore = FableLoreItem(
        matchup_id=matchup.id,
        work_title="Lantern Tales",
        installment="issue 1",
        pinpoint="page 4",
        canon_status="primary_canon",
        body="Lantern throws one glass marble.",
    )
    db.add(lore)
    db.flush()
    db.add_all([
        FableMove(matchup_id=matchup.id, participant_id=lantern.id, move_text="Lantern throws one glass marble.", claimed_source="Lantern Tales, issue 1, page 4"),
        FableMove(matchup_id=matchup.id, participant_id=lantern.id, move_text="Lantern throws a marble that destroys a planet.", claimed_source="Lantern Tales, issue 1, page 4"),
        FableMove(matchup_id=matchup.id, participant_id=comet.id, move_text="Comet reads minds.", claimed_source="Lantern Tales, issue 1, page 4"),
    ])
    db.flush()
    rule_submitted_moves(db, matchup, None)
    return matchup


def _suggest_matchup(db) -> FableMatchup:
    found = _existing(db, SUGGEST_TITLE)
    if found is not None:
        return found
    matchup = FableMatchup(
        title=SUGGEST_TITLE,
        question="DEMO fiction only. A proposed ruling is waiting for a moderator.",
        mode="debate",
        personal_knowledge_only=True,
        referee_mode="ai_suggest",
        canon_only=True,
        automated_analysis="not_implemented",
        automated_referee="deterministic-lore",
    )
    db.add(matchup)
    db.flush()
    lantern = FableParticipant(matchup_id=matchup.id, name="Lantern")
    comet = FableParticipant(matchup_id=matchup.id, name="Comet")
    db.add_all([lantern, comet])
    db.flush()
    db.add(FableLoreItem(
        matchup_id=matchup.id,
        work_title="Lantern Tales",
        installment="issue 1",
        pinpoint="page 4",
        canon_status="primary_canon",
        body="Lantern throws one glass marble.",
    ))
    db.flush()
    db.add(FableMove(
        matchup_id=matchup.id,
        participant_id=lantern.id,
        move_text="Lantern throws one glass marble.",
        claimed_source="Lantern Tales, issue 1, page 4",
    ))
    db.flush()
    rule_submitted_moves(db, matchup, None)
    return matchup


def seed() -> tuple[int, int]:
    db = SessionLocal()
    try:
        auto = _auto_matchup(db)
        suggest = _suggest_matchup(db)
        db.commit()
        proposed = (
            db.query(FableRuling)
            .join(FableMove, FableMove.id == FableRuling.move_id)
            .filter(FableMove.matchup_id == suggest.id, FableRuling.status == "proposed")
            .count()
        )
        print(f"DEMO FABLE matchup {auto.id}: Lantern vs Comet, AI auto-rule. Fiction only.")
        print(f"DEMO FABLE matchup {suggest.id}: proposed rulings waiting: {proposed}. Fiction only.")
        return auto.id, suggest.id
    finally:
        db.close()


if __name__ == "__main__":
    seed()
