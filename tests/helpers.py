"""Shared test helpers — importable from test modules."""

import uuid
from datetime import datetime


def seed_conversation(conn, conv_id=None, status="awaiting_claim_review", **kwargs):
    """Insert a conversation row. Returns the ID."""
    cid = conv_id or f"test_{uuid.uuid4()}"
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO conversations (id, source, processing_status, created_at,
           captured_at, modality, current_stage, run_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cid,
            kwargs.get("source", "test"),
            status,
            now,
            kwargs.get("captured_at", now),
            kwargs.get("modality", "audio"),
            kwargs.get("current_stage", "claim_review"),
            kwargs.get("run_status", "idle"),
        ),
    )
    conn.commit()
    return cid


def seed_contact(conn, entity_id=None, name="Test Contact", networking_app_contact_id=None):
    """Insert a unified_contacts row. Returns the entity ID."""
    eid = entity_id or str(uuid.uuid4())
    conn.execute(
        """INSERT INTO unified_contacts (id, canonical_name, networking_app_contact_id,
           is_confirmed, created_at)
           VALUES (?, ?, ?, 1, datetime('now'))""",
        (eid, name, networking_app_contact_id),
    )
    conn.commit()
    return eid
