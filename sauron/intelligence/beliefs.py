"""Belief layer utilities — truth maintenance, staleness, what-changed snapshots.

Beliefs are DERIVED from claims. This module manages the belief lifecycle:
- Staleness detection (beliefs not confirmed recently)
- What-changed snapshot generation
- Belief queries for game plan generation
- Belief conflict detection
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

# Beliefs not confirmed in this many days become stale
STALENESS_THRESHOLD_DAYS = 90


def detect_stale_beliefs() -> int:
    """Mark beliefs as 'stale' if not confirmed within threshold.

    Returns number of beliefs marked stale.
    """
    conn = get_connection()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALENESS_THRESHOLD_DAYS)).isoformat()

    try:
        result = conn.execute(
            """UPDATE beliefs SET status = 'stale', last_changed_at = ?
               WHERE status IN ('active', 'provisional', 'refined', 'qualified')
               AND last_confirmed_at < ?
               AND last_confirmed_at IS NOT NULL""",
            (datetime.now(timezone.utc).isoformat(), cutoff),
        )
        count = result.rowcount
        conn.commit()
        if count > 0:
            logger.info(f"Marked {count} beliefs as stale (not confirmed in {STALENESS_THRESHOLD_DAYS} days)")
        return count
    except Exception:
        conn.rollback()
        logger.exception("Stale belief detection failed")
        return 0
    finally:
        conn.close()


def generate_what_changed(entity_type: str, entity_id: str, conversation_id: str) -> str | None:
    """Generate a what-changed snapshot for an entity after a conversation.

    Compares current beliefs to previous snapshot and creates a diff summary.
    Returns the change summary or None if nothing meaningful changed.
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()

    try:
        # Get current beliefs for this entity
        current_beliefs = conn.execute(
            """SELECT belief_key, belief_summary, status, confidence
               FROM beliefs WHERE entity_type = ? AND entity_id = ?
               AND status NOT IN ('stale', 'superseded')
               ORDER BY belief_key""",
            (entity_type, entity_id),
        ).fetchall()

        current_state = {
            r["belief_key"]: {
                "summary": r["belief_summary"],
                "status": r["status"],
                "confidence": r["confidence"],
            }
            for r in current_beliefs
        }

        # Get previous snapshot
        prev_snapshot = conn.execute(
            """SELECT old_state_json, new_state_json FROM what_changed_snapshots
               WHERE entity_type = ? AND entity_id = ?
               ORDER BY snapshot_date DESC LIMIT 1""",
            (entity_type, entity_id),
        ).fetchone()

        if prev_snapshot and prev_snapshot["new_state_json"]:
            old_state = json.loads(prev_snapshot["new_state_json"])
        else:
            old_state = {}

        # Compute diff
        changes = []
        new_keys = set(current_state.keys()) - set(old_state.keys())
        removed_keys = set(old_state.keys()) - set(current_state.keys())
        shared_keys = set(current_state.keys()) & set(old_state.keys())

        for key in new_keys:
            changes.append(f"NEW: {current_state[key]['summary']}")

        for key in removed_keys:
            changes.append(f"REMOVED: {old_state[key]['summary']}")

        for key in shared_keys:
            old = old_state[key]
            new = current_state[key]
            if old.get("summary") != new["summary"]:
                changes.append(f"CHANGED: {old.get('summary', '?')} → {new['summary']}")
            elif old.get("status") != new["status"]:
                changes.append(f"STATUS: {key} {old.get('status')} → {new['status']}")

        if not changes:
            return None

        change_summary = "; ".join(changes)

        # Compute significance (0-1)
        significance = min(1.0, len(changes) * 0.2)
        if any(c.startswith("CHANGED:") for c in changes):
            significance = min(1.0, significance + 0.3)

        # Store snapshot
        conn.execute(
            """INSERT INTO what_changed_snapshots
               (id, entity_type, entity_id, snapshot_date, change_summary,
                old_state_json, new_state_json, significance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), entity_type, entity_id, now,
             change_summary, json.dumps(old_state), json.dumps(current_state),
             significance),
        )
        conn.commit()

        logger.info(f"What-changed for {entity_type}/{entity_id}: {len(changes)} changes")
        return change_summary

    except Exception:
        conn.rollback()
        logger.exception(f"What-changed generation failed for {entity_type}/{entity_id}")
        return None
    finally:
        conn.close()


def get_beliefs_for_contact(contact_id: str, limit: int = 30) -> list[dict]:
    """Get active beliefs about a contact for game plan generation."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT belief_key, belief_summary, status, confidence,
                      support_count, contradiction_count,
                      first_observed_at, last_confirmed_at
               FROM beliefs
               WHERE entity_id = ? AND status NOT IN ('stale', 'superseded')
               ORDER BY confidence DESC, last_confirmed_at DESC
               LIMIT ?""",
            (contact_id, limit),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_beliefs_for_topic(topic: str, limit: int = 20) -> list[dict]:
    """Get beliefs about a topic across all entities."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT b.entity_type, b.entity_id, b.belief_key, b.belief_summary,
                      b.status, b.confidence, b.last_confirmed_at,
                      uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE (b.belief_key LIKE ? OR b.belief_summary LIKE ?)
               AND b.status NOT IN ('stale', 'superseded')
               ORDER BY b.confidence DESC
               LIMIT ?""",
            (f"%{topic}%", f"%{topic}%", limit),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_contested_beliefs(limit: int = 20) -> list[dict]:
    """Get beliefs that are contested (conflicting evidence) for triage."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT b.*, uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE b.status = 'contested'
               ORDER BY b.contradiction_count DESC, b.last_changed_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_what_changed_for_entity(
    entity_type: str, entity_id: str, days: int = 30
) -> list[dict]:
    """Get recent what-changed snapshots for an entity."""
    conn = get_connection()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = conn.execute(
            """SELECT snapshot_date, change_summary, significance
               FROM what_changed_snapshots
               WHERE entity_type = ? AND entity_id = ?
               AND snapshot_date > ?
               ORDER BY snapshot_date DESC""",
            (entity_type, entity_id, cutoff),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()
