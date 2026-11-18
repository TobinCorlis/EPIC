"""Demote rc2 verified/archived labels that have no verification event.

Zero is not used. A missing record is unknown, so confidence_score becomes
NULL. The previous label is kept in status_history.
"""
from sqlalchemy import text
from sqlalchemy.engine import Connection

VERIFIED_NOTE = "Marked verified in rc2; no verification record found"
ARCHIVED_NOTE = "Marked archived in rc2; no verification record found"


def demote_legacy_verified_without_events(connection: Connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO status_history (
                subject_type, subject_id, previous_status, new_status, note,
                verification_event_id, created_at
            )
            SELECT 'knowledge_claim', id, status, 'unverified',
                CASE WHEN status = 'archived' THEN :archived_note ELSE :verified_note END,
                NULL, CURRENT_TIMESTAMP
            FROM knowledge_claims
            WHERE status IN ('verified', 'archived')
              AND NOT EXISTS (
                SELECT 1 FROM verification_events
                WHERE subject_type = 'knowledge_claim'
                  AND subject_id = knowledge_claims.id
                  AND CAST(result_status AS TEXT) = CAST(knowledge_claims.status AS TEXT)
              )
            """
        ),
        {"verified_note": VERIFIED_NOTE, "archived_note": ARCHIVED_NOTE},
    )
    connection.execute(
        text(
            """
            UPDATE knowledge_claims
            SET status = 'unverified', confidence_score = NULL
            WHERE status IN ('verified', 'archived')
              AND NOT EXISTS (
                SELECT 1 FROM verification_events
                WHERE subject_type = 'knowledge_claim'
                  AND subject_id = knowledge_claims.id
                  AND CAST(result_status AS TEXT) = CAST(knowledge_claims.status AS TEXT)
              )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO status_history (
                subject_type, subject_id, previous_status, new_status, note,
                verification_event_id, created_at
            )
            SELECT 'argument_node', id, verification_status, 'unverified',
                CASE WHEN verification_status = 'archived' THEN :archived_note ELSE :verified_note END,
                NULL, CURRENT_TIMESTAMP
            FROM argument_nodes
            WHERE verification_status IN ('verified', 'archived')
              AND NOT EXISTS (
                SELECT 1 FROM verification_events
                WHERE subject_type = 'argument_node'
                  AND subject_id = argument_nodes.id
                  AND CAST(result_status AS TEXT) = CAST(argument_nodes.verification_status AS TEXT)
              )
            """
        ),
        {"verified_note": VERIFIED_NOTE, "archived_note": ARCHIVED_NOTE},
    )
    connection.execute(
        text(
            """
            UPDATE argument_nodes
            SET verification_status = 'unverified'
            WHERE verification_status IN ('verified', 'archived')
              AND NOT EXISTS (
                SELECT 1 FROM verification_events
                WHERE subject_type = 'argument_node'
                  AND subject_id = argument_nodes.id
                  AND CAST(result_status AS TEXT) = CAST(argument_nodes.verification_status AS TEXT)
              )
            """
        )
    )
