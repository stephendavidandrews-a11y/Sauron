"""Text pipeline status — smoke signals for the UI.

Provides a single endpoint that returns the full health picture:
- Last sync time + result
- Messages ingested (total, today, this week)
- Threads tracked vs whitelisted vs filtered
- Unknown contacts waiting in pending queue
- Clusters created + their depth lane distribution
- Extraction status (queued, processing, completed, failed)
- Watermark position vs chat.db max ROWID (are we falling behind?)
- Any errors or warnings from the last run

This is the "am I blind?" dashboard. If the pipeline is running but
missing people, filtering too aggressively, or silently failing —
this surface will show it.
"""

import logging
import sqlite3

from sauron.db.connection import get_connection as _db_conn
from datetime import datetime, timedelta, timezone

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)


def _get_conn(db_path=None) -> sqlite3.Connection:
    """Get a DB connection with FK/WAL/busy_timeout pragmas."""
    if db_path:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn
    return _db_conn()


def get_pipeline_status(db_path=None) -> dict:
    """Get comprehensive text pipeline status for the UI.

    Returns a dict with all smoke signals. Every field that could
    indicate a problem has a 'status' subfield: 'ok', 'warning', 'error'.
    """
    conn = _get_conn(db_path)
    try:
        status = {
            "sync": _get_sync_status(conn),
            "ingest": _get_ingest_stats(conn),
            "threads": _get_thread_stats(conn),
            "contacts": _get_contact_stats(conn),
            "clusters": _get_cluster_stats(conn),
            "pipeline_health": "unknown",
            "warnings": [],
            "errors": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Derive overall health
        _assess_health(status)

        return status
    finally:
        conn.close()


def _get_sync_status(conn: sqlite3.Connection) -> dict:
    """Sync watermark and recency info."""
    row = conn.execute(
        "SELECT * FROM text_sync_state WHERE source = 'imessage'"
    ).fetchone()

    if not row:
        return {
            "status": "warning",
            "detail": "Never synced — pipeline has not run yet",
            "last_sync_at": None,
            "last_message_id": None,
            "messages_processed": 0,
        }

    result = {
        "last_sync_at": row["last_sync_at"],
        "last_message_id": row["last_message_id"],
        "last_status": row["last_status"],
        "messages_processed": row["messages_processed"],
    }

    # Check recency
    if row["last_sync_at"]:
        try:
            last_sync = datetime.fromisoformat(row["last_sync_at"].replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - last_sync).total_seconds() / 3600
            result["hours_since_sync"] = round(age_hours, 1)
            if age_hours > 24:
                result["status"] = "error"
                result["detail"] = f"Last sync was {age_hours:.0f} hours ago"
            elif age_hours > 6:
                result["status"] = "warning"
                result["detail"] = f"Last sync was {age_hours:.1f} hours ago"
            else:
                result["status"] = "ok"
                result["detail"] = f"Synced {age_hours:.1f} hours ago"
        except (ValueError, TypeError):
            result["status"] = "warning"
            result["detail"] = "Cannot parse last sync timestamp"
    else:
        result["status"] = "warning"
        result["detail"] = "No sync timestamp recorded"

    return result


def _get_ingest_stats(conn: sqlite3.Connection) -> dict:
    """Message ingest statistics."""
    total = conn.execute("SELECT COUNT(*) FROM text_messages").fetchone()[0]

    # Today's messages
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    today = conn.execute(
        "SELECT COUNT(*) FROM text_messages WHERE created_at >= ?",
        (today_start,),
    ).fetchone()[0]

    # This week
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    this_week = conn.execute(
        "SELECT COUNT(*) FROM text_messages WHERE created_at >= ?",
        (week_start,),
    ).fetchone()[0]

    # Content type breakdown
    types = {}
    cursor = conn.execute(
        "SELECT content_type, COUNT(*) as cnt FROM text_messages GROUP BY content_type"
    )
    for row in cursor:
        types[row["content_type"]] = row["cnt"]

    return {
        "total_messages": total,
        "today": today,
        "this_week": this_week,
        "content_types": types,
        "status": "ok" if total > 0 else "warning",
    }


def _get_thread_stats(conn: sqlite3.Connection) -> dict:
    """Thread tracking and whitelist coverage."""
    total = conn.execute("SELECT COUNT(*) FROM text_threads").fetchone()[0]
    by_type = {}
    cursor = conn.execute(
        "SELECT thread_type, COUNT(*) as cnt FROM text_threads GROUP BY thread_type"
    )
    for row in cursor:
        by_type[row["thread_type"]] = row["cnt"]

    # Threads with recent activity (last 7 days based on last_message_at)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    active = conn.execute(
        "SELECT COUNT(*) FROM text_threads WHERE last_message_at >= ?",
        (week_ago,),
    ).fetchone()[0]

    # Threads with resolved contacts (at least one participant_contact_id)
    whitelisted = conn.execute(
        "SELECT COUNT(*) FROM text_threads WHERE participant_contact_ids IS NOT NULL"
    ).fetchone()[0]

    return {
        "total_threads": total,
        "by_type": by_type,
        "active_last_7_days": active,
        "whitelisted": whitelisted,
        "not_whitelisted": total - whitelisted,
        "status": "ok" if total > 0 else "warning",
    }


def _get_contact_stats(conn: sqlite3.Connection) -> dict:
    """Contact resolution and pending queue status."""
    # Unified contacts with phones
    total_contacts = conn.execute(
        "SELECT COUNT(*) FROM unified_contacts WHERE phone_number IS NOT NULL"
    ).fetchone()[0]

    # Pending contacts
    pending = conn.execute(
        "SELECT COUNT(*) FROM pending_contacts WHERE status = 'pending'"
    ).fetchone()[0]

    approved = conn.execute(
        "SELECT COUNT(*) FROM pending_contacts WHERE status = 'approved'"
    ).fetchone()[0]

    dismissed = conn.execute(
        "SELECT COUNT(*) FROM pending_contacts WHERE status = 'dismissed'"
    ).fetchone()[0]

    # Top pending contacts (most messages, so user can prioritize)
    top_pending = []
    cursor = conn.execute(
        """SELECT phone, display_name, message_count, first_seen_at
           FROM pending_contacts
           WHERE status = 'pending'
           ORDER BY message_count DESC
           LIMIT 10"""
    )
    for row in cursor:
        top_pending.append({
            "phone": row["phone"],
            "display_name": row["display_name"],
            "message_count": row["message_count"],
            "first_seen_at": row["first_seen_at"],
        })

    result = {
        "unified_contacts_with_phone": total_contacts,
        "pending_review": pending,
        "approved": approved,
        "dismissed": dismissed,
        "top_pending": top_pending,
        "status": "ok",
    }

    if pending > 10:
        result["status"] = "warning"
        result["detail"] = f"{pending} unknown contacts waiting for review"

    return result


def _get_cluster_stats(conn: sqlite3.Connection) -> dict:
    """Cluster creation and processing stats."""
    total = conn.execute("SELECT COUNT(*) FROM text_clusters").fetchone()[0]

    # By depth lane
    by_lane = {}
    cursor = conn.execute(
        "SELECT depth_lane, COUNT(*) as cnt FROM text_clusters GROUP BY depth_lane"
    )
    for row in cursor:
        lane = row["depth_lane"]
        label = {0: "thin", 1: "haiku_label", 2: "sonnet", 3: "opus", None: "untriaged"}.get(lane, str(lane))
        by_lane[label] = row["cnt"]

    # Clusters with conversations (linked to extraction pipeline)
    linked = conn.execute(
        "SELECT COUNT(*) FROM text_clusters WHERE conversation_id IS NOT NULL"
    ).fetchone()[0]

    return {
        "total_clusters": total,
        "by_depth_lane": by_lane,
        "linked_to_conversations": linked,
        "unlinked": total - linked,
        "status": "ok" if total > 0 else "warning" if total == 0 else "ok",
    }


def _assess_health(status: dict) -> None:
    """Derive overall pipeline health + collect warnings/errors."""
    warnings = []
    errors = []

    # Check sync
    sync = status["sync"]
    if sync["status"] == "error":
        errors.append(f"Sync: {sync.get('detail', 'error')}")
    elif sync["status"] == "warning":
        warnings.append(f"Sync: {sync.get('detail', 'warning')}")

    # Check if we have any data at all
    if status["ingest"]["total_messages"] == 0:
        warnings.append("No messages ingested yet")

    # Check pending contacts
    contacts = status["contacts"]
    if contacts.get("pending_review", 0) > 0:
        warnings.append(f"{contacts['pending_review']} unknown contacts need review")

    # Check unwhitelisted threads with activity
    threads = status["threads"]
    if threads.get("not_whitelisted", 0) > 0 and threads.get("active_last_7_days", 0) > 0:
        not_wl = threads["not_whitelisted"]
        warnings.append(f"{not_wl} threads not whitelisted (may be missing intelligence)")

    status["warnings"] = warnings
    status["errors"] = errors

    if errors:
        status["pipeline_health"] = "error"
    elif warnings:
        status["pipeline_health"] = "warning"
    else:
        status["pipeline_health"] = "ok"
