"""
sauron/api/learning_api.py

Learning review API — amendment history, correction stats, and learning dashboard data.
"""
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/dashboard")
def learning_dashboard():
    """Get learning system dashboard data — corrections, amendments, contact prefs."""
    conn = get_connection()
    try:
        # Correction stats (from correction_events table)
        total_corrections = conn.execute(
            "SELECT COUNT(*) FROM correction_events"
        ).fetchone()[0]

        corrections_by_type = {}
        for row in conn.execute(
            "SELECT error_type, COUNT(*) as cnt FROM correction_events GROUP BY error_type ORDER BY cnt DESC"
        ).fetchall():
            corrections_by_type[row["error_type"]] = row["cnt"]

        recent_corrections = []
        for row in conn.execute(
            """SELECT ce.id, ce.conversation_id, ce.error_type,
                      ce.old_value, ce.new_value, ce.user_feedback,
                      ce.claim_id, ce.belief_id, ce.created_at
               FROM correction_events ce
               ORDER BY ce.created_at DESC LIMIT 20"""
        ).fetchall():
            recent_corrections.append(dict(row))

        # Amendment history
        amendments = []
        for row in conn.execute(
            """SELECT id, version, amendment_text, source_analysis,
                      correction_count, active, created_at
               FROM prompt_amendments ORDER BY created_at DESC"""
        ).fetchall():
            a = dict(row)
            if a.get("source_analysis"):
                try:
                    a["source_analysis"] = json.loads(a["source_analysis"])
                except (json.JSONDecodeError, TypeError):
                    pass
            amendments.append(a)

        # Contact preferences
        contact_prefs = []
        for row in conn.execute(
            """SELECT cep.*, uc.canonical_name
               FROM contact_extraction_preferences cep
               LEFT JOIN unified_contacts uc ON cep.contact_id = uc.id
               ORDER BY cep.last_updated DESC"""
        ).fetchall():
            contact_prefs.append(dict(row))

        # Pending corrections (not yet folded into amendment)
        latest_amendment_date = conn.execute(
            "SELECT MAX(created_at) FROM prompt_amendments"
        ).fetchone()[0] or "1970-01-01T00:00:00"

        pending_count = conn.execute(
            "SELECT COUNT(*) FROM correction_events WHERE created_at > ?",
            (latest_amendment_date,)
        ).fetchone()[0]

        # Reprocessing effectiveness (Feature 5)
        reprocessing_stats = []
        try:
            reprocess_rows = conn.execute(
                """SELECT amendment_version,
                          SUM(corrections_resolved) as total_resolved,
                          SUM(corrections_regressed) as total_regressed,
                          SUM(claims_reproduced) as total_reproduced,
                          SUM(claims_missed) as total_missed,
                          SUM(claims_new) as total_new,
                          COUNT(*) as conversations_compared
                   FROM reprocessing_comparisons
                   GROUP BY amendment_version
                   ORDER BY MAX(created_at) DESC"""
            ).fetchall()
            reprocessing_stats = [dict(r) for r in reprocess_rows]
        except Exception:
            pass  # Table may not exist yet

        # Amendment effectiveness (Feature 2)
        effectiveness_stats = []
        try:
            eff_rows = conn.execute(
                """SELECT ae.error_type, ae.corrections_before,
                          ae.corrections_after, ae.period_days,
                          ae.effectiveness, ae.amendment_version,
                          ae.computed_at
                   FROM amendment_effectiveness ae
                   ORDER BY ae.computed_at DESC
                   LIMIT 50"""
            ).fetchall()
            effectiveness_stats = [dict(r) for r in eff_rows]
        except Exception:
            pass  # Table may not exist yet

        # Pending resynthesis proposals
        pending_resyntheses = 0
        try:
            resynth_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM belief_resynthesis_proposals WHERE status = 'pending'"
            ).fetchone()
            pending_resyntheses = resynth_row["cnt"] if resynth_row else 0
        except Exception:
            pass

        return {
            "total_corrections": total_corrections,
            "pending_corrections": pending_count,
            "corrections_by_type": corrections_by_type,
            "recent_corrections": recent_corrections,
            "amendments": amendments,
            "active_amendment": next((a for a in amendments if a.get("active")), None),
            "contact_preferences": contact_prefs,
            "reprocessing_stats": reprocessing_stats,
            "effectiveness_stats": effectiveness_stats,
            "pending_resyntheses": pending_resyntheses,
        }
    finally:
        conn.close()


@router.get("/amendments")
def list_amendments():
    """Get all prompt amendments with history."""
    conn = get_connection()
    try:
        amendments = []
        for row in conn.execute(
            """SELECT id, version, amendment_text, source_analysis,
                      correction_count, active, created_at
               FROM prompt_amendments ORDER BY created_at DESC"""
        ).fetchall():
            a = dict(row)
            if a.get("source_analysis"):
                try:
                    a["source_analysis"] = json.loads(a["source_analysis"])
                except (json.JSONDecodeError, TypeError):
                    pass
            amendments.append(a)
        return {"amendments": amendments}
    finally:
        conn.close()


class AmendmentToggle(BaseModel):
    active: bool


@router.put("/amendments/{amendment_id}")
def toggle_amendment(amendment_id: str, body: AmendmentToggle):
    """Activate or deactivate a specific amendment version."""
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM prompt_amendments WHERE id = ?", (amendment_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Amendment not found")

        if body.active:
            # Deactivate all others first
            conn.execute("UPDATE prompt_amendments SET active = FALSE WHERE active = TRUE")
        conn.execute(
            "UPDATE prompt_amendments SET active = ? WHERE id = ?",
            (body.active, amendment_id)
        )
        conn.commit()
        return {"status": "ok", "active": body.active}
    finally:
        conn.close()


class AmendmentEdit(BaseModel):
    amendment_text: str


@router.patch("/amendments/{amendment_id}")
def edit_amendment(amendment_id: str, body: AmendmentEdit):
    """Edit an amendment's text (user tweaking learned rules)."""
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM prompt_amendments WHERE id = ?", (amendment_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Amendment not found")
        conn.execute(
            "UPDATE prompt_amendments SET amendment_text = ? WHERE id = ?",
            (body.amendment_text, amendment_id)
        )
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@router.post("/analyze")
def trigger_learning_analysis():
    """Manually trigger correction analysis and amendment generation."""
    try:
        from sauron.learning.amendments import analyze_corrections_and_amend
        result = analyze_corrections_and_amend()
        if result is None:
            return {
                "status": "no_action",
                "message": "Insufficient corrections to generate a new amendment (need 5+ of same type)",
            }
        return {"status": "generated", "amendment_text": result}
    except Exception as exc:
        logger.exception("Learning analysis failed")
        raise HTTPException(status_code=500, detail=str(exc))


class ContactPrefUpdate(BaseModel):
    commitment_confidence_threshold: float | None = None
    typical_follow_through_rate: float | None = None
    extraction_depth: str | None = None
    vocal_alert_sensitivity: str | None = None
    relationship_importance: float | None = None
    custom_notes: str | None = None


@router.put("/contacts/{contact_id}/preferences")
def update_contact_preferences(contact_id: str, body: ContactPrefUpdate):
    """Update extraction preferences for a specific contact."""
    from sauron.learning.amendments import update_contact_preference

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    for field, value in updates.items():
        update_contact_preference(contact_id, field, value)

    return {"status": "ok", "updated_fields": list(updates.keys())}


@router.get("/contacts/{contact_id}/preferences")
def get_contact_prefs(contact_id: str):
    """Get extraction preferences for a contact."""
    from sauron.learning.amendments import get_contact_preferences
    prefs = get_contact_preferences(contact_id)
    if prefs is None:
        return {"contact_id": contact_id, "preferences": None}
    return {"contact_id": contact_id, "preferences": prefs}
