"""Shared pipeline helpers — status updates and embedding.

Split out to avoid circular imports between processor.py and extraction_runner.py.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _update_status(conn, conversation_id: str, status: str):
    """Update conversation processing status with timestamp for terminal-ish statuses.
    Also writes the unified stage model (current_stage, stage_detail, run_status).
    """
    from sauron.pipeline.stage_model import stage_for_voice_status

    terminal_statuses = (
        "transcribed", "completed", "error",
        "awaiting_speaker_review", "triage_rejected", "awaiting_claim_review",
    )
    now = datetime.now(timezone.utc).isoformat() if status in terminal_statuses else None
    current_stage, stage_detail, run_status = stage_for_voice_status(status)
    conn.execute(
        """UPDATE conversations
           SET processing_status = ?,
               processed_at = COALESCE(?, processed_at),
               current_stage = ?,
               stage_detail = ?,
               run_status = ?
           WHERE id = ?""",
        (status, now, current_stage, stage_detail, run_status, conversation_id),
    )


def _run_embedding(conversation_id: str):
    """Run semantic embedding for all conversation artefacts."""
    try:
        from sauron.embeddings.embedder import embed_conversation
        embed_conversation(conversation_id)
    except Exception:
        logger.exception("Embedding failed (non-fatal)")
