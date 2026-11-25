"""Create a clearly labeled DEMO FABLE matchup with three referee rulings.

Run from the repository root:

    cd backend && PYTHONPATH=. python3 ../scripts/seed_fable_demo.py

The matchup is fiction. It is not factual evidence.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionLocal
from app.models.fable import FableLoreItem, FableMatchup, FableMove, FableParticipant
from app.services.referee import rule_submitted_moves


def seed() -> int:
    db = SessionLocal()
    try:
        matchup = FableMatchup(
            title="DEMO: Lantern vs Comet",
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
            FableMove(
                matchup_id=matchup.id,
                participant_id=lantern.id,
                move_text="Lantern throws one glass marble.",
                claimed_source="Lantern Tales, issue 1, page 4",
            ),
            FableMove(
                matchup_id=matchup.id,
                participant_id=lantern.id,
                move_text="Lantern throws a marble that destroys a planet.",
                claimed_source="Lantern Tales, issue 1, page 4",
            ),
            FableMove(
                matchup_id=matchup.id,
                participant_id=comet.id,
                move_text="Comet reads minds.",
                claimed_source="Lantern Tales, issue 1, page 4",
            ),
        ])
        db.flush()
        rule_submitted_moves(db, matchup, None)
        db.commit()
        print(f"DEMO FABLE matchup {matchup.id}: Lantern vs Comet. Fiction only, not evidence.")
        return matchup.id
    finally:
        db.close()


if __name__ == "__main__":
    seed()
