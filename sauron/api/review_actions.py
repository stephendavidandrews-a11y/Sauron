"""Review lifecycle endpoints extracted from conversations.py.

Contains: flag_conversation, discard_conversation, mark_reviewed.
"""

import logging
from fastapi import APIRouter, HTTPException

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()


@router.patch("/{conversation_id}/flag")
def flag_conversation(conversation_id: str):
    """Flag a conversation for deep review. Removes its claims from Quick Pass."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE conversations SET flagged_for_review = 1 WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
        return {"status": "ok", "conversation_id": conversation_id, "flagged_for_review": True}
    finally:
        conn.close()



@router.patch("/{conversation_id}/discard")
def discard_conversation(conversation_id: str, body: dict = None):
    """Discard a conversation. Terminal status, removes from all review queues.
    Available from speaker_review, triage_rejected, and claim_review stages."""
    conn = get_connection()
    try:
        conv = conn.execute(
            "SELECT processing_status FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        allowed = {"awaiting_speaker_review", "triage_rejected", "awaiting_claim_review"}
        current = conv["processing_status"]
        if current not in allowed:
            raise HTTPException(
                status_code=400,
                detail="Cannot discard from status '%s'. Allowed: %s" % (current, ", ".join(sorted(allowed))),
            )

        reason = (body or {}).get("reason", "user_discarded")

        conn.execute(
            """UPDATE conversations
               SET processing_status = 'discarded',
                   current_stage = 'completed',
                   stage_detail = 'discarded',
                   run_status = 'completed'
               WHERE id = ?""",
            (conversation_id,),
        )

        import uuid as _uuid
        conn.execute(
            "INSERT INTO correction_events (id, conversation_id, error_type, old_value, new_value, correction_source) VALUES (?, ?, 'conversation_discarded', ?, ?, 'manual_ui')",
            (str(_uuid.uuid4()), conversation_id, current, reason),
        )

        conn.commit()
        logger.info("Discarded conversation %s (was %s, reason: %s)", conversation_id[:8], current, reason)
        return {"status": "ok", "conversation_id": conversation_id, "discarded": True}
    finally:
        conn.close()


@router.post("/{conversation_id}/review")
def mark_reviewed(conversation_id: str):
    """Mark a conversation as reviewed and trigger routing to downstream apps."""
    conn = get_connection()
    try:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Set reviewed_at timestamp (status update deferred until after routing)
        conn.execute(
            "UPDATE conversations SET reviewed_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()

        # Route REVIEWED data (corrected DB state, not stale extraction JSON)
        routing_succeeded = False
        try:
            from sauron.routing.reviewed_payload import build_reviewed_payload
            from sauron.routing.router import route_extraction
            reviewed_payload = build_reviewed_payload(conversation_id)
            route_extraction(conversation_id, reviewed_payload)
            routing_succeeded = True

            # Only set routed_at if routing was not held as pending_entity
            # and no failures occurred.
            check_conn = get_connection()
            try:
                pending_or_failed = check_conn.execute(
                    """SELECT COUNT(*) as cnt FROM routing_log
                       WHERE conversation_id = ?
                         AND status IN ('pending_entity', 'failed')""",
                    (conversation_id,),
                ).fetchone()
            finally:
                check_conn.close()

            if not pending_or_failed or pending_or_failed["cnt"] == 0:
                conn.execute(
                    "UPDATE conversations SET routed_at = datetime('now') WHERE id = ?",
                    (conversation_id,),
                )
                conn.commit()
                logger.info(f"Routed reviewed conversation {conversation_id[:8]} (authoritative payload)")
            else:
                logger.info(
                    f"Reviewed conversation {conversation_id[:8]} — routing held "
                    f"({pending_or_failed['cnt']} pending/failed entries in routing_log)"
                )
        except Exception:
            logger.exception(f"Routing failed for {conversation_id[:8]} (non-fatal)")

        # Set terminal status: completed if routing succeeded, routing_failed otherwise
        final_status = 'completed' if routing_succeeded else 'routing_failed'
        conn.execute(
            """UPDATE conversations
               SET processing_status = ?,
                   current_stage = 'completed',
                   stage_detail = ?,
                   run_status = 'completed'
               WHERE id = ?""",
            (final_status, final_status, conversation_id),
        )
        conn.commit()

        # Count correction stats for this conversation (Change 5)
        try:
            stats_row = conn.execute(
                """SELECT
                    (SELECT COUNT(*) FROM event_claims WHERE conversation_id = ? AND review_status = 'user_confirmed') as approved,
                    (SELECT COUNT(*) FROM event_claims WHERE conversation_id = ? AND review_status = 'dismissed') as dismissed,
                    (SELECT COUNT(*) FROM correction_events WHERE conversation_id = ?) as corrections,
                    (SELECT COUNT(DISTINCT b.id) FROM beliefs b
                     JOIN belief_evidence be ON be.belief_id = b.id
                     JOIN event_claims ec ON be.claim_id = ec.id
                     WHERE ec.conversation_id = ? AND b.status = 'under_review') as beliefs_affected
                """,
                (conversation_id, conversation_id, conversation_id, conversation_id),
            ).fetchone()
            review_stats = {
                "approved": stats_row["approved"] or 0,
                "dismissed": stats_row["dismissed"] or 0,
                "corrections": stats_row["corrections"] or 0,
                "beliefs_affected": stats_row["beliefs_affected"] or 0,
            }
        except Exception:
            review_stats = None

        return {"status": "ok", "conversation_id": conversation_id, "reviewed": True, "stats": review_stats}
    finally:
        conn.close()
