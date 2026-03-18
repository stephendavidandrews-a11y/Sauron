"""Text pipeline API — status, sync trigger, pending contacts.

Mounted at /api/text/ in main.py.
"""

import logging
import threading

from fastapi import APIRouter, HTTPException

from sauron.text.status import get_pipeline_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/text", tags=["text"])


@router.get("/status")
async def text_pipeline_status():
    """Get text pipeline health status (smoke signals).

    Returns sync state, ingest stats, thread coverage,
    pending contacts, cluster stats, and overall health.
    """
    try:
        return get_pipeline_status()
    except Exception as e:
        logger.exception("Failed to get text pipeline status")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads")
async def list_threads():
    """List all tracked text threads with stats."""
    from sauron.text.ingest import get_thread_stats
    try:
        return get_thread_stats()
    except Exception as e:
        logger.exception("Failed to list threads")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending-contacts")
async def list_pending_contacts():
    """List contacts in the pending review queue."""
    from sauron.db.connection import get_connection
    try:
        conn = get_connection()
        cursor = conn.execute(
            """SELECT id, phone, display_name, source, first_seen_at,
                      last_seen_at, message_count, thread_ids, status
               FROM pending_contacts
               ORDER BY
                   CASE status WHEN 'pending' THEN 0 WHEN 'deferred' THEN 1 ELSE 2 END,
                   message_count DESC"""
        )
        results = [dict(row) for row in cursor]
        conn.close()
        return results
    except Exception as e:
        logger.exception("Failed to list pending contacts")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def trigger_text_sync(dry_run: bool = False):
    """Manually trigger a text sync cycle.

    Query params:
        dry_run: If true, ingest + cluster but skip extraction (no API calls)
    """
    from sauron.text.sync import sync_text

    # Run sync in background thread to avoid blocking the API
    def _run():
        try:
            result = sync_text(dry_run=dry_run)
            logger.info("[API] Text sync completed: %s", result)
        except Exception as e:
            logger.error("[API] Text sync failed: %s", e, exc_info=True)

    from sauron.executor import submit_background_job
    submit_background_job(_run)

    return {"status": "sync_started", "dry_run": dry_run}


@router.post("/pending-contacts/{pending_id}/approve")
async def approve_contact(pending_id: str, body: dict):
    """Approve a pending contact and create a unified_contact.

    Body JSON: {"name": "...", "organization": "...", "title": "...", "email": "..."}
    Only 'name' is required.
    """
    from sauron.text.pending_contacts import approve_pending_contact

    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    try:
        result = approve_pending_contact(
            pending_id, name,
            organization=body.get("organization"),
            title=body.get("title"),
            email=body.get("email"),
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to approve contact %s", pending_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pending-contacts/{pending_id}/dismiss")
async def dismiss_contact(pending_id: str):
    """Dismiss a pending contact permanently."""
    from sauron.text.pending_contacts import dismiss_pending_contact

    try:
        return dismiss_pending_contact(pending_id)
    except Exception as e:
        logger.exception("Failed to dismiss contact %s", pending_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pending-contacts/{pending_id}/defer")
async def defer_contact(pending_id: str):
    """Defer a pending contact for later review."""
    from sauron.text.pending_contacts import defer_pending_contact

    try:
        return defer_pending_contact(pending_id)
    except Exception as e:
        logger.exception("Failed to defer contact %s", pending_id)
        raise HTTPException(status_code=500, detail=str(e))
