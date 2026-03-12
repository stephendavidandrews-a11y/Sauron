"""sauron/routing/provisional.py — Store provisional org suggestions for review."""
import uuid
import sqlite3
import logging

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)


def store_provisional_org(
    raw_name: str,
    normalized_name: str | None,
    conversation_id: str,
    source_context: str | None = None,
    resolution_source_context: str | None = None,
    suggested_by: str | None = None,
) -> bool:
    """Store a provisional org suggestion for later review.

    Dedup by (normalized_name, conversation_id) — same org from same conversation
    is only stored once.

    Returns True if stored, False if dedup skipped.
    """
    norm = (normalized_name or raw_name).lower().strip()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        existing = conn.execute(
            "SELECT id FROM provisional_org_suggestions WHERE normalized_name = ? AND conversation_id = ?",
            (norm, conversation_id)
        ).fetchone()

        if existing:
            logger.debug(f"Provisional org dedup: '{norm}' already stored for conversation {conversation_id[:8]}")
            return False

        conn.execute("""
            INSERT INTO provisional_org_suggestions
            (id, raw_name, normalized_name, conversation_id, source_context,
             resolution_source_context, status, suggested_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, datetime('now'))
        """, (
            str(uuid.uuid4()),
            raw_name,
            norm,
            conversation_id,
            (source_context or "")[:500],  # truncate for sanity
            resolution_source_context,
            suggested_by,
        ))
        conn.commit()
        logger.info(f"Stored provisional org: '{raw_name}' (norm: '{norm}') from {suggested_by}")
        return True
    except Exception as e:
        logger.error(f"Failed to store provisional org '{raw_name}': {e}")
        return False
    finally:
        conn.close()
