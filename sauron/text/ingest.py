"""Text ingest — store threads and messages in sauron.db with dedup.

Consumes normalized TextEvent objects from any source adapter and persists
them into the text_threads / text_messages tables. All operations are
idempotent: re-ingesting the same messages produces zero duplicates.

Dedup keys:
- text_threads: (source, thread_identifier) UNIQUE
- text_messages: (thread_id, source_message_id) UNIQUE
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from sauron.config import DB_PATH
from sauron.text.models import TextEvent

logger = logging.getLogger(__name__)


def _get_conn(db_path=None) -> sqlite3.Connection:
    """Get a DB connection with WAL mode and foreign keys enabled."""
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_thread(
    conn: sqlite3.Connection,
    event: TextEvent,
) -> str:
    """Upsert a text_thread record. Returns the thread ID.

    On first encounter: creates the thread.
    On subsequent encounters: updates last_message_at and participant list.
    Never duplicates a thread (UNIQUE on source + thread_identifier).
    """
    # Check if thread exists
    cursor = conn.execute(
        "SELECT id, participant_phones FROM text_threads WHERE source = ? AND thread_identifier = ?",
        (event.source, event.thread_identifier),
    )
    existing = cursor.fetchone()

    participants_json = json.dumps(event.participant_phones) if event.participant_phones else None

    if existing:
        thread_id = existing["id"]
        # Update metadata: last_message_at, participants (may grow over time)
        conn.execute(
            """UPDATE text_threads
               SET last_message_at = MAX(COALESCE(last_message_at, ''), ?),
                   participant_phones = COALESCE(?, participant_phones),
                   display_name = COALESCE(?, display_name)
               WHERE id = ?""",
            (
                event.timestamp.isoformat(),
                participants_json,
                event.group_name,
                thread_id,
            ),
        )
        return thread_id

    # Create new thread
    thread_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO text_threads
           (id, source, thread_identifier, thread_type, display_name,
            participant_phones, first_message_at, last_message_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            thread_id,
            event.source,
            event.thread_identifier,
            event.thread_type,
            event.group_name,
            participants_json,
            event.timestamp.isoformat(),
            event.timestamp.isoformat(),
        ),
    )
    logger.debug("Created thread %s for %s/%s", thread_id, event.source, event.thread_identifier)
    return thread_id


def _store_message(
    conn: sqlite3.Connection,
    event: TextEvent,
    thread_id: str,
) -> bool:
    """Store a single message. Returns True if inserted, False if already exists.

    Dedup key: (thread_id, source_message_id) UNIQUE.
    """
    try:
        conn.execute(
            """INSERT INTO text_messages
               (id, thread_id, source_message_id, sender_phone, direction,
                content, content_type, timestamp, is_group_message,
                attachment_type, attachment_filename, attachment_url,
                refers_to_message_id, is_from_me, raw_metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                thread_id,
                event.source_message_id,
                event.sender_phone,
                event.direction,
                event.content,
                event.content_type,
                event.timestamp.isoformat(),
                1 if event.is_group else 0,
                event.attachment_type,
                event.attachment_filename,
                event.attachment_url,
                event.refers_to_message_id,
                1 if event.is_from_me else 0,
                json.dumps(event.raw_metadata) if event.raw_metadata else None,
            ),
        )
        return True
    except sqlite3.IntegrityError:
        # Duplicate (thread_id, source_message_id) — skip silently
        return False


def ingest_events(
    events: list[TextEvent],
    db_path=None,
) -> dict:
    """Ingest a batch of TextEvents into sauron.db.

    Returns a summary dict:
    {
        "total": int,
        "inserted": int,
        "skipped_duplicate": int,
        "threads_created": int,
        "threads_updated": int,
        "errors": int,
    }
    """
    conn = _get_conn(db_path)
    stats = {
        "total": len(events),
        "inserted": 0,
        "skipped_duplicate": 0,
        "threads_created": 0,
        "threads_updated": 0,
        "errors": 0,
    }

    # Track which threads existed before this batch
    existing_threads: set[tuple[str, str]] = set()
    cursor = conn.execute("SELECT source, thread_identifier FROM text_threads")
    for row in cursor:
        existing_threads.add((row["source"], row["thread_identifier"]))

    try:
        for event in events:
            try:
                thread_key = (event.source, event.thread_identifier)
                was_new = thread_key not in existing_threads

                thread_id = _ensure_thread(conn, event)

                if was_new and thread_key not in existing_threads:
                    stats["threads_created"] += 1
                    existing_threads.add(thread_key)
                elif not was_new:
                    # Only count as updated if metadata changed (we always try to update)
                    stats["threads_updated"] += 1

                if _store_message(conn, event, thread_id):
                    stats["inserted"] += 1
                else:
                    stats["skipped_duplicate"] += 1

            except Exception as e:
                logger.error("Error ingesting event %s: %s", event.source_message_id, e)
                stats["errors"] += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "Ingest complete: %d inserted, %d skipped (dup), %d threads created, %d errors",
        stats["inserted"], stats["skipped_duplicate"], stats["threads_created"], stats["errors"],
    )
    return stats


def get_sync_watermark(source: str = "imessage", db_path=None) -> int:
    """Get the last synced message ROWID for a source. Returns 0 if never synced."""
    conn = _get_conn(db_path)
    try:
        cursor = conn.execute(
            "SELECT last_message_id FROM text_sync_state WHERE source = ?",
            (source,),
        )
        row = cursor.fetchone()
        return int(row["last_message_id"]) if row and row["last_message_id"] else 0
    finally:
        conn.close()


def advance_watermark(
    source: str,
    last_message_id: str,
    messages_processed: int,
    db_path=None,
) -> None:
    """Advance the sync watermark after successful ingest.

    Only call this AFTER all messages in the batch are successfully stored.
    """
    conn = _get_conn(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO text_sync_state (id, source, last_sync_at, last_message_id, last_status, messages_processed)
               VALUES (?, ?, ?, ?, 'completed', ?)
               ON CONFLICT(source) DO UPDATE SET
                   last_sync_at = excluded.last_sync_at,
                   last_message_id = excluded.last_message_id,
                   last_status = excluded.last_status,
                   messages_processed = text_sync_state.messages_processed + excluded.messages_processed""",
            (str(uuid.uuid4()), source, now, last_message_id, messages_processed),
        )
        conn.commit()
        logger.info("Watermark advanced: source=%s, last_id=%s, processed=%d", source, last_message_id, messages_processed)
    finally:
        conn.close()


def get_thread_stats(db_path=None) -> list[dict]:
    """Get summary stats for all ingested threads (for diagnostics)."""
    conn = _get_conn(db_path)
    try:
        cursor = conn.execute("""
            SELECT
                t.id,
                t.source,
                t.thread_identifier,
                t.thread_type,
                t.display_name,
                t.first_message_at,
                t.last_message_at,
                COUNT(m.id) as message_count
            FROM text_threads t
            LEFT JOIN text_messages m ON m.thread_id = t.id
            GROUP BY t.id
            ORDER BY t.last_message_at DESC
        """)
        return [dict(row) for row in cursor]
    finally:
        conn.close()
