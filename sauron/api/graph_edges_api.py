"""Graph edge editing API endpoints.

Endpoints for listing, editing, confirming, dismissing, and creating
graph edges (relationship links between entities).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph-edges", tags=["graph-edges"])


# -- Migration helper ---------------------------------------------------------

def _ensure_review_status_column():
    """Add review_status column to graph_edges if it doesn't exist."""
    conn = get_connection()
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(graph_edges)").fetchall()]
        if "review_status" not in cols:
            conn.execute("ALTER TABLE graph_edges ADD COLUMN review_status TEXT DEFAULT 'pending'")
            conn.commit()
            logger.info("Added review_status column to graph_edges")
    finally:
        conn.close()


# Run on import so column exists before any endpoint is called
_ensure_review_status_column()


# -- Pydantic models ---------------------------------------------------------

class EdgeUpdateRequest(BaseModel):
    relationship_type: Optional[str] = None
    source_entity_id: Optional[str] = None
    target_entity_id: Optional[str] = None
    review_status: Optional[str] = None  # confirmed | dismissed | pending


class EdgeCreateRequest(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    source_conversation_id: Optional[str] = None


# -- Helpers ------------------------------------------------------------------

def _edge_to_dict(row) -> dict:
    """Convert a graph_edges Row to a response dict."""
    keys = row.keys()
    return {
        "id": row["id"],
        "source_entity_id": row["from_entity"],
        "source_type": row["from_type"],
        "target_entity_id": row["to_entity"],
        "target_type": row["to_type"],
        "relationship_type": row["edge_type"],
        "strength": row["strength"],
        "source_conversation_id": row["source_conversation_id"],
        "review_status": row["review_status"] if "review_status" in keys else "pending",
        "observed_at": row["observed_at"],
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


def _resolve_name(conn, entity_id: str) -> Optional[str]:
    """Look up canonical_name from unified_contacts."""
    row = conn.execute(
        "SELECT canonical_name FROM unified_contacts WHERE id = ?",
        (entity_id,),
    ).fetchone()
    return row["canonical_name"] if row else None


def _get_edge_or_404(conn, edge_id: str):
    row = conn.execute("SELECT * FROM graph_edges WHERE id = ?", (edge_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Edge {edge_id} not found")
    return row


# -- Endpoints ----------------------------------------------------------------

@router.get("/conversation/{conversation_id}")
def list_edges_for_conversation(conversation_id: str):
    """List all graph edges inferred from a conversation."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM graph_edges WHERE source_conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        ).fetchall()

        edges = []
        for row in rows:
            d = _edge_to_dict(row)
            d["source_name"] = _resolve_name(conn, row["from_entity"])
            d["target_name"] = _resolve_name(conn, row["to_entity"])
            edges.append(d)

        return {"edges": edges, "count": len(edges)}
    finally:
        conn.close()


@router.put("/{edge_id}")
def update_edge(edge_id: str, body: EdgeUpdateRequest):
    """Edit a graph edge. Only provided fields are updated."""
    conn = get_connection()
    try:
        _get_edge_or_404(conn, edge_id)

        updates = []
        params = []

        if body.relationship_type is not None:
            updates.append("edge_type = ?")
            params.append(body.relationship_type)
        if body.source_entity_id is not None:
            updates.append("from_entity = ?")
            params.append(body.source_entity_id)
        if body.target_entity_id is not None:
            updates.append("to_entity = ?")
            params.append(body.target_entity_id)
        if body.review_status is not None:
            if body.review_status not in ("confirmed", "dismissed", "pending"):
                raise HTTPException(
                    status_code=400,
                    detail="review_status must be confirmed, dismissed, or pending",
                )
            updates.append("review_status = ?")
            params.append(body.review_status)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(edge_id)
        sql = f"UPDATE graph_edges SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, params)
        conn.commit()

        row = conn.execute("SELECT * FROM graph_edges WHERE id = ?", (edge_id,)).fetchone()
        d = _edge_to_dict(row)
        d["source_name"] = _resolve_name(conn, row["from_entity"])
        d["target_name"] = _resolve_name(conn, row["to_entity"])
        return d
    finally:
        conn.close()


@router.post("/{edge_id}/confirm")
def confirm_edge(edge_id: str):
    """Confirm an inferred edge."""
    conn = get_connection()
    try:
        _get_edge_or_404(conn, edge_id)
        conn.execute(
            "UPDATE graph_edges SET review_status = 'confirmed' WHERE id = ?",
            (edge_id,),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM graph_edges WHERE id = ?", (edge_id,)).fetchone()
        d = _edge_to_dict(row)
        d["source_name"] = _resolve_name(conn, row["from_entity"])
        d["target_name"] = _resolve_name(conn, row["to_entity"])
        return d
    finally:
        conn.close()


@router.post("/{edge_id}/dismiss")
def dismiss_edge(edge_id: str):
    """Dismiss an incorrect edge."""
    conn = get_connection()
    try:
        _get_edge_or_404(conn, edge_id)
        conn.execute(
            "UPDATE graph_edges SET review_status = 'dismissed' WHERE id = ?",
            (edge_id,),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM graph_edges WHERE id = ?", (edge_id,)).fetchone()
        d = _edge_to_dict(row)
        d["source_name"] = _resolve_name(conn, row["from_entity"])
        d["target_name"] = _resolve_name(conn, row["to_entity"])
        return d
    finally:
        conn.close()


@router.post("")
def create_edge(body: EdgeCreateRequest):
    """Manually create a graph edge (user-created, auto-confirmed)."""
    conn = get_connection()
    try:
        edge_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO graph_edges
               (id, from_entity, from_type, to_entity, to_type, edge_type,
                strength, source_conversation_id, observed_at, review_status, created_at)
               VALUES (?, ?, 'contact', ?, 'contact', ?, 1.0, ?, ?, 'confirmed', ?)""",
            (
                edge_id,
                body.source_entity_id,
                body.target_entity_id,
                body.relationship_type,
                body.source_conversation_id,
                now,
                now,
            ),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM graph_edges WHERE id = ?", (edge_id,)).fetchone()
        d = _edge_to_dict(row)
        d["source_name"] = _resolve_name(conn, row["from_entity"])
        d["target_name"] = _resolve_name(conn, row["to_entity"])
        return d
    finally:
        conn.close()
