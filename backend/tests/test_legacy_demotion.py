from fastapi.testclient import TestClient

from app.core.database import SessionLocal, engine
from app.main import app
from app.models.argument import ArgumentNode, VerificationStatus
from app.models.knowledge import KnowledgeClaim, KnowledgeStatus
from app.models.status_history import StatusHistory
from app.models.verification import RecordedVerificationStatus, VerificationEvent, VerificationSubject
from app.services.knowledge_matching import fingerprint_claim, normalize_claim
from app.services.legacy_status import ARCHIVED_NOTE, VERIFIED_NOTE, demote_legacy_verified_without_events

client = TestClient(app)


def test_demotion_nulls_confidence_and_keeps_the_old_label():
    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": "Legacy dossier", "question": "Was the rc2 label recorded?"},
    ).json()
    debate = client.post(
        "/debates",
        json={"title": "Legacy debate", "fixed_question": "Was the rc2 label recorded?"},
    ).json()
    claim = client.post(
        f"/debates/{debate['id']}/claims",
        json={"body": "The agency report records 12 hours.", "claim_type": "factual"},
    ).json()
    participant = client.post(
        f"/debates/{debate['id']}/participants",
        json={"display_name": "Legacy debater", "role": "debater", "side": "affirmative"},
    ).json()
    node = client.post(
        f"/debates/{debate['id']}/arguments",
        json={"participant_id": participant["id"], "claim_id": claim["id"], "node_type": "premise", "body": "Direct evidence."},
    ).json()
    keeper = client.post(
        "/auth/register",
        json={"email": "legacy-keeper@example.com", "display_name": "Keeper", "password": "verysecure123"},
    ).json()
    body = "The agency report records 12 hours of storage coverage."
    with SessionLocal() as db:
        kept = KnowledgeClaim(
            dossier_id=dossier["id"],
            body="A recorded verification stays verified.",
            normalized_body=normalize_claim("A recorded verification stays verified."),
            fingerprint=fingerprint_claim("A recorded verification stays verified."),
            status=KnowledgeStatus.verified,
            confidence_score=0.4,
        )
        legacy = KnowledgeClaim(
            dossier_id=dossier["id"],
            originating_claim_id=claim["id"],
            body=body,
            normalized_body=normalize_claim(body),
            fingerprint=fingerprint_claim(body),
            status=KnowledgeStatus.verified,
            confidence_score=1.0,
        )
        archived = KnowledgeClaim(
            dossier_id=dossier["id"],
            body="An archived label without a record.",
            normalized_body=normalize_claim("An archived label without a record."),
            fingerprint=fingerprint_claim("An archived label without a record."),
            status=KnowledgeStatus.archived,
            confidence_score=0.2,
        )
        db.add_all([kept, legacy, archived])
        db.flush()
        db.add(
            VerificationEvent(
                subject_type=VerificationSubject.knowledge_claim,
                subject_id=kept.id,
                result_status=RecordedVerificationStatus.verified,
                actor_user_id=keeper["user"]["id"],
                method="Compared the retained archive",
                snapshot_hash="sha256:kept",
            )
        )
        argument = db.get(ArgumentNode, node["id"])
        argument.verification_status = VerificationStatus.verified
        db.commit()
        with engine.begin() as connection:
            demote_legacy_verified_without_events(connection)
        db.expire_all()
        legacy_row = db.get(KnowledgeClaim, legacy.id)
        archived_row = db.get(KnowledgeClaim, archived.id)
        kept_row = db.get(KnowledgeClaim, kept.id)
        assert legacy_row.status == KnowledgeStatus.unverified
        assert legacy_row.confidence_score is None
        assert archived_row.status == KnowledgeStatus.unverified
        assert archived_row.confidence_score is None
        assert kept_row.status == KnowledgeStatus.verified
        assert kept_row.confidence_score == 0.4
        notes = {
            row.note
            for row in db.query(StatusHistory).filter(StatusHistory.subject_type == "knowledge_claim").all()
        }
        assert VERIFIED_NOTE in notes
        assert ARCHIVED_NOTE in notes
        argument = db.get(ArgumentNode, node["id"])
        assert argument.verification_status == VerificationStatus.unverified

    listed = client.get(f"/debates/{debate['id']}/claims").json()
    assert any(note["note"] == VERIFIED_NOTE for note in listed[0]["status_notes"])
    visible = client.get(f"/knowledge/dossiers/{dossier['id']}/claims").json()
    legacy_visible = next(row for row in visible if row["body"] == body)
    assert legacy_visible["confidence_score"] is None
    assert legacy_visible["status_history"][0]["note"] == VERIFIED_NOTE
