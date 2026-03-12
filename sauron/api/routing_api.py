"""Routing API endpoints for routing summaries and pending routes."""

import json
import logging

from fastapi import APIRouter, Query

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/routing", tags=["routing"])


@router.get("/pending")
def list_pending_routes(by: str = Query("entity", pattern="^(entity|conversation)$")):
    """List pending (held) object routes grouped by entity or conversation.

    Query params:
        by: 'entity' (default) groups by blocked_on_entity with count per entity
            'conversation' groups by conversation_id with count per conversation
    """
    conn = get_connection()
    try:
        if by == "entity":
            rows = conn.execute(
                """SELECT blocked_on_entity, COUNT(*) as count,
                          GROUP_CONCAT(DISTINCT route_type) as route_types,
                          MIN(created_at) as oldest
                   FROM pending_object_routes
                   WHERE status = 'pending'
                   GROUP BY blocked_on_entity
                   ORDER BY count DESC"""
            ).fetchall()
            return [
                {
                    "blocked_on_entity": r["blocked_on_entity"],
                    "count": r["count"],
                    "route_types": r["route_types"].split(",") if r["route_types"] else [],
                    "oldest": r["oldest"],
                }
                for r in rows
            ]
        else:
            rows = conn.execute(
                """SELECT conversation_id, COUNT(*) as count,
                          GROUP_CONCAT(DISTINCT route_type) as route_types,
                          GROUP_CONCAT(DISTINCT blocked_on_entity) as blocked_entities,
                          MIN(created_at) as oldest
                   FROM pending_object_routes
                   WHERE status = 'pending'
                   GROUP BY conversation_id
                   ORDER BY count DESC"""
            ).fetchall()
            return [
                {
                    "conversation_id": r["conversation_id"],
                    "count": r["count"],
                    "route_types": r["route_types"].split(",") if r["route_types"] else [],
                    "blocked_entities": r["blocked_entities"].split(",") if r["blocked_entities"] else [],
                    "oldest": r["oldest"],
                }
                for r in rows
            ]
    finally:
        conn.close()


# Mount conversation-level routing summary under /conversations prefix
conv_routing_router = APIRouter(prefix="/conversations", tags=["conversations"])


@conv_routing_router.get("/{conversation_id}/routing-summary")
def get_routing_summary(conversation_id: str):
    """Return all routing summaries for a conversation, newest first.

    Includes JSON-parsed lane data for each summary.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, conversation_id, routing_attempt_id, trigger_type,
                      final_state, core_lanes, secondary_lanes, pending_entities,
                      warning_count, error_count, created_at
               FROM routing_summaries
               WHERE conversation_id = ?
               ORDER BY created_at DESC""",
            (conversation_id,)
        ).fetchall()

        results = []
        for r in rows:
            row_dict = dict(r)
            # Parse JSON fields
            for field in ("core_lanes", "secondary_lanes", "pending_entities"):
                raw = row_dict.get(field)
                if raw:
                    try:
                        row_dict[field] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(row_dict)

        return results
    finally:
        conn.close()
