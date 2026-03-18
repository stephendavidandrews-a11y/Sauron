"""Diagnostics and system status endpoints.

Provides observability into:
- Database connectivity
- Pipeline status (pending/processing/completed/failed counts)
- Routing status (pending_entity/sent/failed counts)
- Dependency availability (Networking App reachability)
- Scheduler status
"""

import logging
import os
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter

from sauron.db.connection import get_connection
from sauron.config import NETWORKING_APP_URL

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/status")
def system_status():
    """Full system status — database, pipeline, routing, dependencies."""
    status = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "database": _check_database(),
        "pipeline": _check_pipeline(),
        "routing": _check_routing(),
        "dependencies": _check_dependencies(),
    }

    # Overall health
    degraded = any(
        v.get("status") == "error"
        for v in status.values()
        if isinstance(v, dict)
    )
    status["overall"] = "degraded" if degraded else "healthy"

    return status


@router.get("/pipeline")
def pipeline_detail():
    """Detailed pipeline status — recent conversations by processing stage."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT processing_status, COUNT(*) as count
               FROM conversations
               GROUP BY processing_status"""
        ).fetchall()
        by_status = {r["processing_status"] or "unknown": r["count"] for r in rows}

        # Recent failures
        failures = conn.execute(
            """SELECT id, source, processing_status, blocking_reason,
                      created_at, processed_at
               FROM conversations
               WHERE processing_status IN ('failed', 'error')
               ORDER BY created_at DESC LIMIT 10"""
        ).fetchall()

        # Stuck conversations (processing for > 30 min)
        stuck = conn.execute(
            """SELECT id, source, processing_status, current_stage, created_at
               FROM conversations
               WHERE processing_status = 'processing'
                 AND created_at < datetime('now', '-30 minutes')
               ORDER BY created_at ASC"""
        ).fetchall()

        return {
            "by_status": by_status,
            "recent_failures": [dict(r) for r in failures],
            "stuck_conversations": [dict(r) for r in stuck],
        }
    finally:
        conn.close()


@router.get("/routing")
def routing_detail():
    """Detailed routing status — pending, failed, recent successes."""
    conn = get_connection()
    try:
        # Counts by status
        rows = conn.execute(
            """SELECT status, COUNT(*) as count
               FROM routing_log
               GROUP BY status"""
        ).fetchall()
        by_status = {r["status"]: r["count"] for r in rows}

        # Recent failures
        failures = conn.execute(
            """SELECT id, conversation_id, object_class, last_error,
                      attempts, last_attempt_at
               FROM routing_log
               WHERE status = 'failed'
               ORDER BY last_attempt_at DESC LIMIT 10"""
        ).fetchall()

        # Pending entities
        pending = conn.execute(
            """SELECT rl.entity_id, uc.canonical_name, COUNT(*) as held_count
               FROM routing_log rl
               LEFT JOIN unified_contacts uc ON rl.entity_id = uc.id
               WHERE rl.status = 'pending_entity'
               GROUP BY rl.entity_id"""
        ).fetchall()

        return {
            "by_status": by_status,
            "recent_failures": [dict(r) for r in failures],
            "pending_entities": [dict(r) for r in pending],
        }
    finally:
        conn.close()


def _check_database():
    try:
        conn = get_connection()
        try:
            conn.execute("SELECT 1")
            count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            return {"status": "ok", "conversations": count}
        finally:
            conn.close()
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _check_pipeline():
    try:
        conn = get_connection()
        pending = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE processing_status = 'pending'"
        ).fetchone()[0]
        processing = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE processing_status = 'processing'"
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE processing_status IN ('failed', 'error')"
        ).fetchone()[0]
        conn.close()
        status = "error" if failed > 0 else ("busy" if processing > 0 else "ok")
        return {"status": status, "pending": pending, "processing": processing, "failed": failed}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _check_routing():
    try:
        conn = get_connection()
        failed = conn.execute(
            "SELECT COUNT(*) FROM routing_log WHERE status = 'failed'"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM routing_log WHERE status = 'pending_entity'"
        ).fetchone()[0]
        conn.close()
        status = "error" if failed > 5 else ("warning" if pending > 10 else "ok")
        return {"status": status, "failed": failed, "pending_entity": pending}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _check_dependencies():
    deps = {}
    # Networking App
    try:
        _key = os.environ.get("NETWORKING_APP_API_KEY", "")
        _hdrs = {"X-API-Key": _key} if _key else {}
        r = httpx.get(f"{NETWORKING_APP_URL}/api/health", headers=_hdrs, timeout=3.0)
        deps["networking_app"] = {
            "status": "ok" if r.status_code == 200 else "degraded",
            "response_code": r.status_code,
        }
    except httpx.ConnectError:
        deps["networking_app"] = {"status": "unreachable", "url": NETWORKING_APP_URL}
    except Exception as e:
        deps["networking_app"] = {"status": "error", "detail": str(e)[:200]}
    return deps
