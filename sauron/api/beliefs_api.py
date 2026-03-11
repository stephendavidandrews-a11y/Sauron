"""Beliefs API -- query beliefs, review evidence, track transitions.

Endpoints:
  GET /beliefs                  -- list beliefs with optional filters
  GET /beliefs/stats            -- belief counts by status and family
  GET /beliefs/recent           -- beliefs changed in last N days
  GET /beliefs/transitions/recent -- recent transitions across all beliefs
  GET /beliefs/contested        -- contested beliefs by contradiction count
  GET /beliefs/contact/{id}     -- beliefs for a specific contact
  GET /beliefs/topic/{t}        -- search beliefs by topic
  GET /beliefs/what-changed/{entity_type}/{entity_id} -- what-changed snapshots
  GET /beliefs/{id}/evidence    -- full evidence chain for a belief
  GET /beliefs/{id}/transitions -- transition history for a belief
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/beliefs", tags=["beliefs"])


# -- Fixed-path routes first (before parameterized routes) --


@router.get("/stats")
async def belief_stats():
    """Belief counts by status and status family."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM beliefs GROUP BY status"
        ).fetchall()
        stats = {r["status"]: r["count"] for r in rows}
        total = sum(stats.values())
        families = {
            "solid": stats.get("active", 0) + stats.get("refined", 0),
            "shifting": stats.get("provisional", 0) + stats.get("qualified", 0) + stats.get("time_bounded", 0),
            "contested": stats.get("contested", 0),
            "stale": stats.get("stale", 0),
            "under_review": stats.get("under_review", 0),
        }
        return {"total": total, "by_status": stats, "by_family": families}
    finally:
        conn.close()


@router.get("/recent")
async def recent_beliefs(days: int = 7, limit: int = 50):
    """Beliefs changed in last N days."""
    conn = get_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT b.*, uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE b.last_changed_at > ?
               ORDER BY b.last_changed_at DESC
               LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/transitions/recent")
async def recent_transitions(days: int = 14, limit: int = 100):
    """All transitions across all beliefs in the last N days, for Recent Movement tab."""
    conn = get_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT bt.id, bt.belief_id, bt.old_status, bt.new_status,
                      bt.driver, bt.cause_summary, bt.source_conversation_id,
                      bt.source_correction_id, bt.created_at,
                      b.belief_summary, b.entity_type, b.entity_id,
                      b.status as current_status, b.confidence,
                      b.support_count, b.contradiction_count,
                      b.belief_key,
                      uc.canonical_name as entity_name
               FROM belief_transitions bt
               JOIN beliefs b ON bt.belief_id = b.id
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE bt.created_at > ?
               ORDER BY bt.created_at DESC
               LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/contested")
async def contested_beliefs(limit: int = 20):
    """List contested beliefs, ordered by contradiction count."""
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


@router.get("/contact/{contact_id}")
async def beliefs_by_contact(contact_id: str, limit: int = 30):
    """Beliefs for a specific contact."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT b.*, uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE b.entity_id = ?
               ORDER BY b.confidence DESC, b.last_confirmed_at DESC
               LIMIT ?""",
            (contact_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/topic/{topic}")
async def beliefs_by_topic(topic: str, limit: int = 20):
    """Search beliefs by topic."""
    conn = get_connection()
    try:
        pattern = f"%{topic}%"
        rows = conn.execute(
            """SELECT b.*, uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE (b.belief_key LIKE ? OR b.belief_summary LIKE ?)
               AND b.status NOT IN ('stale', 'superseded')
               ORDER BY b.confidence DESC
               LIMIT ?""",
            (pattern, pattern, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/what-changed/{entity_type}/{entity_id}")
async def what_changed(entity_type: str, entity_id: str, days: int = 30):
    """What-changed snapshots for an entity."""
    conn = get_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT * FROM what_changed_snapshots
               WHERE entity_type = ? AND entity_id = ?
               AND snapshot_date > ?
               ORDER BY snapshot_date DESC""",
            (entity_type, entity_id, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# -- Parameterized routes (after fixed-path routes) --


@router.get("/{belief_id}/evidence")
async def belief_evidence(belief_id: str):
    """Full evidence chain for a belief: claims with quotes, episode titles, conversation sources."""
    conn = get_connection()
    try:
        belief = conn.execute(
            """SELECT b.*, uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE b.id = ?""",
            (belief_id,),
        ).fetchone()
        if not belief:
            raise HTTPException(404, "Belief not found")

        evidence = conn.execute(
            """SELECT be.id as evidence_id, be.weight, be.evidence_role,
                      ec.id as claim_id, ec.claim_text, ec.claim_type,
                      ec.evidence_quote, ec.confidence as claim_confidence,
                      ec.subject_name, ec.modality,
                      ec.conversation_id,
                      c.source as conversation_source, c.captured_at as conversation_date,
                      ee.title as episode_title, ee.summary as episode_summary
               FROM belief_evidence be
               JOIN event_claims ec ON be.claim_id = ec.id
               LEFT JOIN event_episodes ee ON ec.episode_id = ee.id
               LEFT JOIN conversations c ON ec.conversation_id = c.id
               WHERE be.belief_id = ?
               ORDER BY be.evidence_role, ec.confidence DESC""",
            (belief_id,),
        ).fetchall()

        return {
            "belief": dict(belief),
            "evidence": [dict(e) for e in evidence],
        }
    finally:
        conn.close()


@router.get("/{belief_id}/transitions")
async def belief_transitions(belief_id: str):
    """Transition history for a single belief, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT bt.*, b.belief_summary
               FROM belief_transitions bt
               JOIN beliefs b ON bt.belief_id = b.id
               WHERE bt.belief_id = ?
               ORDER BY bt.created_at DESC""",
            (belief_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# -- Enhanced list endpoint (last, with filters) --


@router.get("")
async def list_beliefs(
    limit: int = 100,
    entity_type: str = None,
    status: str = None,
    status_family: str = None,
):
    """List beliefs with optional filters."""
    conditions = ["b.status != 'superseded'"]
    params = []

    if entity_type:
        conditions.append("b.entity_type = ?")
        params.append(entity_type)

    if status:
        conditions.append("b.status = ?")
        params.append(status)
    elif status_family:
        family_map = {
            "solid": ("active", "refined"),
            "shifting": ("provisional", "qualified", "time_bounded"),
            "contested": ("contested",),
            "stale": ("stale",),
            "under_review": ("under_review",),
        }
        statuses = family_map.get(status_family, ())
        if statuses:
            placeholders = ",".join("?" * len(statuses))
            conditions.append(f"b.status IN ({placeholders})")
            params.extend(statuses)

    where = " AND ".join(conditions)
    params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(
            f"""SELECT b.*, uc.canonical_name as entity_name
                FROM beliefs b
                LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
                WHERE {where}
                ORDER BY b.last_changed_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Belief re-synthesis proposal endpoints (Feature 1)
# ---------------------------------------------------------------------------


@router.get("/resynthesis/pending")
async def pending_resyntheses(limit: int = 50):
    """List pending re-synthesis proposals with belief details."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT brp.*,
                      b.belief_summary, b.belief_key, b.entity_type,
                      b.entity_id, b.status as current_belief_status,
                      b.confidence as current_confidence,
                      b.support_count, b.contradiction_count,
                      uc.canonical_name as entity_name
               FROM belief_resynthesis_proposals brp
               JOIN beliefs b ON brp.belief_id = b.id
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE brp.status = 'pending'
               ORDER BY brp.created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/resynthesis/{proposal_id}/accept")
async def accept_resynthesis(proposal_id: str):
    """Apply proposed summary/status/confidence, mark resolved."""
    conn = get_connection()
    try:
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz

        proposal = conn.execute(
            "SELECT * FROM belief_resynthesis_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        proposal = dict(proposal)

        if proposal["status"] != "pending":
            raise HTTPException(400, "Proposal already resolved")

        belief_id = proposal["belief_id"]

        # Get current belief status for transition logging
        belief = conn.execute(
            "SELECT status FROM beliefs WHERE id = ?", (belief_id,)
        ).fetchone()
        old_status = belief["status"] if belief else "unknown"

        # Apply the proposal
        conn.execute(
            """UPDATE beliefs
               SET belief_summary = ?,
                   status = ?,
                   confidence = ?,
                   last_changed_at = ?
               WHERE id = ?""",
            (
                proposal["proposed_summary"],
                proposal["proposed_status"],
                proposal["proposed_confidence"],
                _dt.now(_tz.utc).isoformat(),
                belief_id,
            ),
        )

        # Log transition
        conn.execute(
            """INSERT INTO belief_transitions
               (id, belief_id, old_status, new_status, driver, cause_summary)
               VALUES (?, ?, ?, ?, 'resynthesis', ?)""",
            (
                str(_uuid.uuid4()),
                belief_id,
                old_status,
                proposal["proposed_status"],
                proposal.get("reasoning", "Re-synthesis accepted"),
            ),
        )

        # Mark proposal as accepted
        conn.execute(
            """UPDATE belief_resynthesis_proposals
               SET status = 'accepted', resolved_at = ?
               WHERE id = ?""",
            (_dt.now(_tz.utc).isoformat(), proposal_id),
        )

        conn.commit()
        return {"status": "ok", "belief_id": belief_id, "new_status": proposal["proposed_status"]}
    finally:
        conn.close()


@router.post("/resynthesis/{proposal_id}/reject")
async def reject_resynthesis(proposal_id: str):
    """Discard proposal, mark resolved. Belief stays under_review for manual handling."""
    conn = get_connection()
    try:
        from datetime import datetime as _dt, timezone as _tz

        proposal = conn.execute(
            "SELECT * FROM belief_resynthesis_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if dict(proposal)["status"] != "pending":
            raise HTTPException(400, "Proposal already resolved")

        conn.execute(
            """UPDATE belief_resynthesis_proposals
               SET status = 'rejected', resolved_at = ?
               WHERE id = ?""",
            (_dt.now(_tz.utc).isoformat(), proposal_id),
        )
        conn.commit()
        return {"status": "ok", "proposal_id": proposal_id}
    finally:
        conn.close()


@router.post("/resynthesis/{proposal_id}/edit")
async def edit_resynthesis(proposal_id: str, body: dict):
    """Apply with user edits to summary/status/confidence."""
    conn = get_connection()
    try:
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz

        proposal = conn.execute(
            "SELECT * FROM belief_resynthesis_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        proposal = dict(proposal)

        if proposal["status"] != "pending":
            raise HTTPException(400, "Proposal already resolved")

        belief_id = proposal["belief_id"]
        summary = body.get("summary", proposal["proposed_summary"])
        status = body.get("status", proposal["proposed_status"])
        confidence = body.get("confidence", proposal["proposed_confidence"])

        # Get current belief status for transition logging
        belief = conn.execute(
            "SELECT status FROM beliefs WHERE id = ?", (belief_id,)
        ).fetchone()
        old_status = belief["status"] if belief else "unknown"

        # Apply edited version
        conn.execute(
            """UPDATE beliefs
               SET belief_summary = ?,
                   status = ?,
                   confidence = ?,
                   last_changed_at = ?
               WHERE id = ?""",
            (summary, status, confidence, _dt.now(_tz.utc).isoformat(), belief_id),
        )

        # Log transition
        conn.execute(
            """INSERT INTO belief_transitions
               (id, belief_id, old_status, new_status, driver, cause_summary)
               VALUES (?, ?, ?, ?, 'resynthesis', ?)""",
            (
                str(_uuid.uuid4()),
                belief_id,
                old_status,
                status,
                "Re-synthesis accepted with edits",
            ),
        )

        # Mark proposal as edited
        conn.execute(
            """UPDATE belief_resynthesis_proposals
               SET status = 'edited', resolved_at = ?,
                   proposed_summary = ?, proposed_status = ?, proposed_confidence = ?
               WHERE id = ?""",
            (_dt.now(_tz.utc).isoformat(), summary, status, confidence, proposal_id),
        )

        conn.commit()
        return {"status": "ok", "belief_id": belief_id, "new_status": status}
    finally:
        conn.close()
