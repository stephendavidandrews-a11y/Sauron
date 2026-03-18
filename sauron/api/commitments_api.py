"""
sauron/api/commitments_api.py

API router for the Commitments tracker tab.

Endpoints:
  GET   /commitments             - list commitments with filters
  GET   /commitments/stats       - summary counts by direction x firmness x status
  PATCH /commitments/:id/status  - update tracker_status / snoozed_until
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/commitments", tags=["commitments-tracker"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class StatusUpdate(BaseModel):
    tracker_status: str  # open | done | cancelled | deferred
    snoozed_until: str | None = None  # YYYY-MM-DD or null


# ---------------------------------------------------------------------------
# GET /commitments - list with filters
# ---------------------------------------------------------------------------

@router.get("")
def list_commitments(
    direction: Optional[str] = Query(None, description="owed_by_me | owed_to_me | mutual"),
    status: Optional[str] = Query("open", description="open | done | cancelled | deferred | all"),
    firmness: Optional[str] = Query(None, description="Comma-separated: required,concrete,intentional,tentative,social"),
    contact: Optional[str] = Query(None, description="Filter by subject_name (partial match)"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List commitment claims with tracker filters."""
    conn = get_connection()
    try:
        conditions = ["ec.claim_type = 'commitment'"]
        params: list = []

        if direction:
            directions = [d.strip() for d in direction.split(",")]
            placeholders = ",".join("?" for _ in directions)
            conditions.append(f"ec.direction IN ({placeholders})")
            params.extend(directions)

        if status and status != "all":
            conditions.append("COALESCE(ec.tracker_status, 'open') = ?")
            params.append(status)

        if firmness:
            firmness_list = [f.strip() for f in firmness.split(",")]
            placeholders = ",".join("?" for _ in firmness_list)
            conditions.append(f"ec.firmness IN ({placeholders})")
            params.extend(firmness_list)

        if contact:
            conditions.append("ec.subject_name LIKE ?")
            params.append(f"%{contact}%")

        where = " AND ".join(conditions)

        query = f"""
            SELECT
                ec.id,
                ec.conversation_id,
                ec.claim_text,
                ec.subject_name,
                ec.direction,
                ec.firmness,
                ec.due_date,
                ec.date_confidence,
                ec.date_note,
                ec.time_horizon,
                ec.has_specific_action,
                ec.has_deadline,
                ec.has_condition,
                ec.condition_text,
                ec.condition_trigger,
                ec.recurrence,
                ec.review_status,
                COALESCE(ec.tracker_status, 'open') as tracker_status,
                ec.snoozed_until,
                ec.confidence,
                ec.importance,
                ec.created_at,
                c.title as conversation_title,
                c.captured_at as conversation_date
            FROM event_claims ec
            LEFT JOIN conversations c ON ec.conversation_id = c.id
            WHERE {where}
            ORDER BY
                CASE WHEN ec.due_date IS NOT NULL AND ec.due_date < date('now') AND COALESCE(ec.tracker_status, 'open') = 'open' THEN 0 ELSE 1 END,
                CASE ec.firmness
                    WHEN 'required' THEN 0
                    WHEN 'concrete' THEN 1
                    WHEN 'intentional' THEN 2
                    WHEN 'tentative' THEN 3
                    WHEN 'social' THEN 4
                    ELSE 5
                END,
                ec.due_date ASC NULLS LAST,
                ec.created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# GET /commitments/stats - badge counts
# ---------------------------------------------------------------------------

@router.get("/stats")
def commitment_stats():
    """Summary counts for the commitments tracker."""
    conn = get_connection()
    try:
        i_owe = conn.execute("""
            SELECT
                COALESCE(tracker_status, 'open') as status,
                firmness,
                COUNT(*) as count,
                SUM(CASE WHEN due_date IS NOT NULL AND due_date < date('now')
                    AND COALESCE(tracker_status, 'open') = 'open' THEN 1 ELSE 0 END) as overdue
            FROM event_claims
            WHERE claim_type = 'commitment'
              AND direction IN ('owed_by_me', 'mutual')
            GROUP BY COALESCE(tracker_status, 'open'), firmness
        """).fetchall()

        owed_to_me = conn.execute("""
            SELECT
                COALESCE(tracker_status, 'open') as status,
                firmness,
                COUNT(*) as count,
                SUM(CASE WHEN due_date IS NOT NULL AND due_date < date('now')
                    AND COALESCE(tracker_status, 'open') = 'open' THEN 1 ELSE 0 END) as overdue
            FROM event_claims
            WHERE claim_type = 'commitment'
              AND direction IN ('owed_to_me', 'mutual')
            GROUP BY COALESCE(tracker_status, 'open'), firmness
        """).fetchall()

        def summarize(rows):
            total_open = 0
            total_done = 0
            total_overdue = 0
            by_firmness = {}
            for r in rows:
                d = dict(r)
                f = d.get("firmness") or "unknown"
                s = d.get("status", "open")
                c = d.get("count", 0)
                o = d.get("overdue", 0)
                if s == "open":
                    total_open += c
                    total_overdue += o
                elif s == "done":
                    total_done += c
                if f not in by_firmness:
                    by_firmness[f] = {"open": 0, "done": 0, "overdue": 0}
                if s == "open":
                    by_firmness[f]["open"] += c
                    by_firmness[f]["overdue"] += o
                elif s == "done":
                    by_firmness[f]["done"] += c
            return {
                "open": total_open,
                "done": total_done,
                "overdue": total_overdue,
                "by_firmness": by_firmness,
            }

        i_owe_stats = summarize(i_owe)
        owed_to_me_stats = summarize(owed_to_me)

        return {
            "i_owe": i_owe_stats,
            "owed_to_me": owed_to_me_stats,
            "badge_count": i_owe_stats["overdue"],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PATCH /commitments/:id/status - update tracker status
# ---------------------------------------------------------------------------

@router.patch("/{claim_id}/status")
def update_commitment_status(claim_id: str, body: StatusUpdate):
    """Update the tracker_status of a commitment claim."""
    valid = {"open", "done", "cancelled", "deferred"}
    if body.tracker_status not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid}",
        )

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM event_claims WHERE id = ? AND claim_type = 'commitment'",
            (claim_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Commitment not found")

        conn.execute(
            "UPDATE event_claims SET tracker_status = ?, snoozed_until = ? WHERE id = ?",
            (body.tracker_status, body.snoozed_until, claim_id),
        )
        conn.commit()

        updated = conn.execute(
            """SELECT id, claim_text, direction, firmness, due_date,
                      COALESCE(tracker_status, 'open') as tracker_status, snoozed_until
               FROM event_claims WHERE id = ?""",
            (claim_id,),
        ).fetchone()
        return dict(updated)
    finally:
        conn.close()
