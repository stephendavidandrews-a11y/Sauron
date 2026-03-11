"""Routing log management for Sauron → Networking App integration.

Handles logging, pending-entity holds, failure tracking, and release triggers.
See Integration Spec v2, Sections 11.4 and 13.
"""

import json
import logging
import uuid
from datetime import datetime

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

# Maximum retry attempts for failed routes
MAX_RETRY_ATTEMPTS = 5


def log_route(
    conversation_id: str,
    target_system: str,
    object_class: str,
    status: str,
    payload: dict,
    entity_id: str | None = None,
    error: str | None = None,
    networking_item_id: str | None = None,
    conn=None,
) -> str:
    """Write a routing log entry.

    Returns the log entry ID.
    """
    should_close = conn is None
    if conn is None:
        conn = get_connection()

    try:
        log_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        conn.execute(
            """INSERT INTO routing_log
               (id, conversation_id, target_system, route_type, object_class,
                status, entity_id, attempts, last_attempt_at, last_error,
                payload_json, networking_item_id, created_at)
               VALUES (?, ?, ?, 'direct_write', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log_id,
                conversation_id,
                target_system,
                object_class,
                status,
                entity_id,
                1 if status in ("sent", "failed") else 0,
                now if status in ("sent", "failed") else None,
                error,
                json.dumps(payload) if payload else None,
                networking_item_id,
                now,
            ),
        )
        if should_close:
            conn.commit()
        return log_id
    finally:
        if should_close:
            conn.close()


def log_pending_entity(
    conversation_id: str,
    entity_id: str,
    payload: dict,
    conn=None,
) -> str:
    """Log a pending-entity hold for a conversation that can't route yet.

    The payload is stored so it can be sent later when the entity gets
    a networking_app_contact_id.
    """
    return log_route(
        conversation_id=conversation_id,
        target_system="networking",
        object_class="conversation_bundle",
        status="pending_entity",
        payload=payload,
        entity_id=entity_id,
        conn=conn,
    )


def log_routing_failure(
    conversation_id: str,
    object_class: str,
    payload: dict,
    error: str,
    conn=None,
) -> str:
    """Log a routing failure."""
    return log_route(
        conversation_id=conversation_id,
        target_system="networking",
        object_class=object_class,
        status="failed",
        payload=payload,
        error=error,
        conn=conn,
    )


def log_routing_success(
    conversation_id: str,
    object_class: str,
    payload: dict,
    networking_item_id: str | None = None,
    conn=None,
) -> str:
    """Log a successful route."""
    return log_route(
        conversation_id=conversation_id,
        target_system="networking",
        object_class=object_class,
        status="sent",
        payload=payload,
        networking_item_id=networking_item_id,
        conn=conn,
    )


def get_pending_routes_for_entity(entity_id: str, conn=None) -> list[dict]:
    """Get all pending_entity routes for a given unified_contacts entity.

    Returns list of routing_log rows as dicts.
    """
    should_close = conn is None
    if conn is None:
        conn = get_connection()

    try:
        rows = conn.execute(
            """SELECT * FROM routing_log
               WHERE entity_id = ? AND status = 'pending_entity'
               ORDER BY created_at""",
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if should_close:
            conn.close()


def release_pending_routes(entity_id: str, networking_app_contact_id: str, conn=None):
    """Release all pending routes for an entity that now has a networking_app_contact_id.

    Sends stored payloads to the Networking App and updates routing_log status.
    Also sets conversations.routed_at for conversations that were held.

    This is called from:
    - graph.py confirm_provisional_contact (after push returns an ID)
    - graph.py link_provisional_contact (after merge into confirmed contact)
    - sync.py sync_contacts_from_networking_app (after sync populates IDs)
    """
    should_close = conn is None
    if conn is None:
        conn = get_connection()

    try:
        pending = get_pending_routes_for_entity(entity_id, conn)
        if not pending:
            return

        logger.info(
            f"Releasing {len(pending)} pending route(s) for entity {entity_id[:8]} "
            f"(networking_app_contact_id={networking_app_contact_id})"
        )

        from sauron.routing.networking import route_to_networking_app

        for route in pending:
            conversation_id = route["conversation_id"]
            payload = json.loads(route["payload_json"]) if route["payload_json"] else {}

            try:
                # Route the stored payload with the now-resolved contact ID
                route_to_networking_app(
                    conversation_id,
                    payload,
                    networking_app_contact_id=networking_app_contact_id,
                )

                # Update routing log to sent
                now = datetime.utcnow().isoformat()
                conn.execute(
                    """UPDATE routing_log
                       SET status = 'sent',
                           attempts = attempts + 1,
                           last_attempt_at = ?
                       WHERE id = ?""",
                    (now, route["id"]),
                )

                # Set routed_at on the conversation
                conn.execute(
                    "UPDATE conversations SET routed_at = datetime('now') WHERE id = ?",
                    (conversation_id,),
                )

                logger.info(f"Released pending route for conversation {conversation_id[:8]}")

            except Exception as e:
                # Mark as failed instead
                now = datetime.utcnow().isoformat()
                conn.execute(
                    """UPDATE routing_log
                       SET status = 'failed',
                           attempts = attempts + 1,
                           last_attempt_at = ?,
                           last_error = ?
                       WHERE id = ?""",
                    (now, str(e)[:500], route["id"]),
                )
                logger.exception(
                    f"Failed to release pending route for conversation {conversation_id[:8]}"
                )

        if should_close:
            conn.commit()
    finally:
        if should_close:
            conn.close()


def get_failed_routes(limit: int = 50, conn=None) -> list[dict]:
    """Get failed routes eligible for retry."""
    should_close = conn is None
    if conn is None:
        conn = get_connection()

    try:
        rows = conn.execute(
            """SELECT * FROM routing_log
               WHERE status = 'failed'
                 AND attempts < ?
               ORDER BY last_attempt_at
               LIMIT ?""",
            (MAX_RETRY_ATTEMPTS, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if should_close:
            conn.close()


def get_routing_status(conn=None) -> dict:
    """Get routing status summary for Today page."""
    should_close = conn is None
    if conn is None:
        conn = get_connection()

    try:
        row = conn.execute(
            """SELECT
                (SELECT COUNT(*) FROM routing_log WHERE status = 'pending_entity') as pending_entity_count,
                (SELECT COUNT(*) FROM routing_log WHERE status = 'failed') as failed_count,
                (SELECT COUNT(*) FROM routing_log WHERE status = 'sent') as sent_count,
                (SELECT COUNT(DISTINCT conversation_id) FROM routing_log WHERE status = 'pending_entity') as pending_conversations,
                (SELECT COUNT(DISTINCT conversation_id) FROM routing_log WHERE status = 'failed') as failed_conversations
            """
        ).fetchone()
        return dict(row) if row else {}
    finally:
        if should_close:
            conn.close()
