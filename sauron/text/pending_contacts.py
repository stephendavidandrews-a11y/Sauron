"""Pending contacts queue management.

Handles unknown phone numbers encountered during text ingestion.
Contacts sit in pending queue until human review: approve (create
unified_contact), dismiss (ignore permanently), or defer (check later).
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)


def _get_conn(db_path=None) -> sqlite3.Connection:
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def get_pending_contacts(db_path=None) -> list[dict]:
    """Get all pending contacts for review."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute("""
            SELECT id, phone, display_name, source, first_seen_at,
                   last_seen_at, message_count, thread_ids, status, created_at
            FROM pending_contacts
            WHERE status = 'pending'
            ORDER BY message_count DESC, first_seen_at ASC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def approve_pending_contact(
    pending_id: str,
    name: str,
    organization: str | None = None,
    title: str | None = None,
    email: str | None = None,
    notes: str | None = None,
    db_path=None,
) -> dict:
    """Approve a pending contact — creates unified_contact entry.

    Args:
        pending_id: pending_contacts.id
        name: Canonical name for the contact
        organization: Optional org name
        title: Optional job title
        email: Optional email address
        notes: Optional notes

    Returns:
        dict with contact_id and status
    """
    conn = _get_conn(db_path)
    try:
        pending = conn.execute(
            "SELECT * FROM pending_contacts WHERE id = ?", (pending_id,)
        ).fetchone()

        if not pending:
            return {"error": f"Pending contact {pending_id} not found"}

        if pending["status"] != "pending":
            return {"error": f"Contact already {pending['status']}"}

        # Create unified_contact
        contact_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        conn.execute("""
            INSERT INTO unified_contacts
                (id, canonical_name, phone_number, email, is_confirmed,
                 current_title, current_organization, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            contact_id,
            name,
            pending["phone"],
            email,
            1,  # confirmed since human approved
            title,
            organization,
            now_iso,
        ))

        # Update pending record
        conn.execute("""
            UPDATE pending_contacts
            SET status = 'approved', resolved_contact_id = ?, reviewed_at = ?
            WHERE id = ?
        """, (contact_id, now_iso, pending_id))

        conn.commit()

        logger.info(
            "Approved pending contact %s → unified_contact %s (%s, phone=%s)",
            pending_id, contact_id[:8], name, pending["phone"],
        )

        return {
            "status": "approved",
            "contact_id": contact_id,
            "name": name,
            "phone": pending["phone"],
        }

    finally:
        conn.close()


def dismiss_pending_contact(pending_id: str, db_path=None) -> dict:
    """Dismiss a pending contact — permanently ignored."""
    conn = _get_conn(db_path)
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE pending_contacts
            SET status = 'dismissed', reviewed_at = ?
            WHERE id = ? AND status = 'pending'
        """, (now_iso, pending_id))
        conn.commit()

        logger.info("Dismissed pending contact %s", pending_id)
        return {"status": "dismissed", "id": pending_id}
    finally:
        conn.close()


def defer_pending_contact(pending_id: str, db_path=None) -> dict:
    """Defer a pending contact — stays pending but marked as seen."""
    conn = _get_conn(db_path)
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE pending_contacts
            SET status = 'deferred', reviewed_at = ?
            WHERE id = ? AND status = 'pending'
        """, (now_iso, pending_id))
        conn.commit()

        logger.info("Deferred pending contact %s", pending_id)
        return {"status": "deferred", "id": pending_id}
    finally:
        conn.close()
