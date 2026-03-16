"""sauron/api/provisional_orgs_api.py — CRUD for provisional org suggestions."""
import json
import logging
import sqlite3

from sauron.db.connection import get_connection
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from sauron.config import DB_PATH, NETWORKING_APP_URL

logger = logging.getLogger(__name__)
router = APIRouter()


def _ensure_unified_entity(conn, org_name: str, networking_org_id: str = None, is_confirmed: bool = True):
    """Create or update a unified_entity for an organization. Returns entity_id."""
    import uuid as _uuid
    normalized = org_name.strip()
    # Check if already exists
    existing = conn.execute(
        "SELECT id FROM unified_entities WHERE entity_type='organization' AND LOWER(canonical_name) = ?",
        (normalized.lower(),),
    ).fetchone()
    if existing:
        entity_id = existing[0] if isinstance(existing, tuple) else existing["id"]
        # Update confirmation status and org_id if needed
        conn.execute(
            "UPDATE unified_entities SET is_confirmed = 1 WHERE id = ? AND is_confirmed = 0",
            (entity_id,),
        )
        if networking_org_id:
            conn.execute(
                "UPDATE entity_organizations SET networking_app_org_id = ? WHERE entity_id = ? AND networking_app_org_id IS NULL",
                (networking_org_id, entity_id),
            )
        return entity_id

    # Create new
    entity_id = str(_uuid.uuid4())
    conn.execute(
        """INSERT INTO unified_entities (id, entity_type, canonical_name, is_confirmed, observation_count, created_at)
           VALUES (?, 'organization', ?, ?, 1, datetime('now'))""",
        (entity_id, normalized, 1 if is_confirmed else 0),
    )
    conn.execute(
        "INSERT INTO entity_organizations (entity_id, networking_app_org_id) VALUES (?, ?)",
        (entity_id, networking_org_id),
    )
    return entity_id

TIMEOUT = 15.0


def _get_conn():
    return get_connection()


# ── Models ──

class ApproveRequest(BaseModel):
    parentOrganizationId: str | None = None


class MergeRequest(BaseModel):
    targetOrgId: str


# ── Endpoints ──

@router.get("/provisional-orgs")
def list_provisional_orgs(
    status: str = Query("pending"),
    limit: int = Query(100, le=500),
):
    """List provisional org suggestions, grouped by normalized_name."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT p.*, c.captured_at as conversation_date
            FROM provisional_org_suggestions p
            LEFT JOIN conversations c ON p.conversation_id = c.id
            WHERE p.status = ?
            ORDER BY p.created_at DESC
            LIMIT ?
        """, (status, limit)).fetchall()

        # Group by normalized_name
        groups = {}
        for row in rows:
            d = dict(row)
            norm = d["normalized_name"]
            if norm not in groups:
                groups[norm] = {
                    "normalized_name": norm,
                    "display_name": d["raw_name"],
                    "count": 0,
                    "suggestions": [],
                    "suggested_by": set(),
                    "first_seen": d["created_at"],
                }
            groups[norm]["count"] += 1
            groups[norm]["suggestions"].append(d)
            if d.get("suggested_by"):
                groups[norm]["suggested_by"].add(d["suggested_by"])
            # Use earliest raw_name as display
            if d["created_at"] < groups[norm]["first_seen"]:
                groups[norm]["first_seen"] = d["created_at"]
                groups[norm]["display_name"] = d["raw_name"]

        # Convert sets to lists for JSON serialization
        result = []
        for g in groups.values():
            g["suggested_by"] = list(g["suggested_by"])
            result.append(g)

        return {"groups": result, "total": len(result)}
    finally:
        conn.close()


@router.get("/provisional-orgs/search-orgs")
def search_networking_orgs(q: str = Query(..., min_length=1)):
    """Proxy search to Networking App organizations API for merge target selection."""
    try:
        resp = httpx.get(
            f"{NETWORKING_APP_URL}/api/organizations",
            params={"q": q},
            timeout=TIMEOUT,
        )
        if resp.status_code >= 300:
            raise HTTPException(status_code=502, detail="Networking App error")
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Cannot reach Networking App")


@router.get("/provisional-orgs/{suggestion_id}")
def get_provisional_org(suggestion_id: str):
    """Get a single provisional org suggestion."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM provisional_org_suggestions WHERE id = ?",
            (suggestion_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        return dict(row)
    finally:
        conn.close()


@router.post("/provisional-orgs/{suggestion_id}/approve")
def approve_provisional_org(suggestion_id: str, body: ApproveRequest = ApproveRequest()):
    """Approve a provisional org: create it in Networking App."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM provisional_org_suggestions WHERE id = ?",
            (suggestion_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        suggestion = dict(row)
        if suggestion["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Suggestion already {suggestion['status']}"
            )

        # Create org in Networking App
        create_payload = {"name": suggestion["raw_name"]}
        if body.parentOrganizationId:
            create_payload["parentOrganizationId"] = body.parentOrganizationId

        try:
            resp = httpx.post(
                f"{NETWORKING_APP_URL}/api/organizations",
                json=create_payload,
                timeout=TIMEOUT,
            )
            if resp.status_code >= 300:
                raise HTTPException(
                    status_code=502,
                    detail=f"Networking App error: {resp.status_code} - {resp.text[:200]}"
                )
            org_data = resp.json()
            org_id = org_data.get("id")
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502,
                detail="Cannot reach Networking App"
            )

        # Store metadata for future route replay
        resolved_meta = json.dumps({
            "parentOrganizationId": body.parentOrganizationId,
            "org_name": org_data.get("name"),
            "conversation_id": suggestion["conversation_id"],
            "source_context": suggestion.get("source_context"),
            "suggested_by": suggestion.get("suggested_by"),
        })

        # Update all pending suggestions with same normalized_name
        norm = suggestion["normalized_name"]
        now = datetime.utcnow().isoformat()
        conn.execute("""
            UPDATE provisional_org_suggestions
            SET status = 'approved', resolved_org_id = ?, resolved_metadata = ?, resolved_at = ?
            WHERE normalized_name = ? AND status = 'pending'
        """, (org_id, resolved_meta, now, norm))
        conn.commit()

        # E2: Create/update unified_entity for this org
        try:
            entity_id = _ensure_unified_entity(conn, suggestion["raw_name"], org_id, is_confirmed=True)
            conn.commit()
            logger.info(f"Approved provisional org '{suggestion['raw_name']}' -> org_id={org_id}, entity_id={entity_id}")
        except Exception:
            logger.exception("Failed to create unified_entity for approved org (non-fatal)")
            logger.info(f"Approved provisional org '{suggestion['raw_name']}' -> org_id={org_id}")
        return {
            "status": "approved",
            "org_id": org_id,
            "org_name": org_data.get("name"),
            "updated_count": conn.execute(
                "SELECT changes()"
            ).fetchone()[0],
        }
    finally:
        conn.close()


@router.post("/provisional-orgs/{suggestion_id}/merge")
def merge_provisional_org(suggestion_id: str, body: MergeRequest):
    """Merge a provisional org suggestion with an existing org."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM provisional_org_suggestions WHERE id = ?",
            (suggestion_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        suggestion = dict(row)
        if suggestion["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Suggestion already {suggestion['status']}"
            )

        # Store metadata for future replay
        resolved_meta = json.dumps({
            "merged_into_org_id": body.targetOrgId,
            "conversation_id": suggestion["conversation_id"],
            "source_context": suggestion.get("source_context"),
            "suggested_by": suggestion.get("suggested_by"),
        })

        # Update all pending with same normalized_name
        norm = suggestion["normalized_name"]
        now = datetime.utcnow().isoformat()
        conn.execute("""
            UPDATE provisional_org_suggestions
            SET status = 'merged', resolved_org_id = ?, resolved_metadata = ?, resolved_at = ?
            WHERE normalized_name = ? AND status = 'pending'
        """, (body.targetOrgId, resolved_meta, now, norm))
        conn.commit()

        # E2: Create/update unified_entity for the merge target
        try:
            entity_id = _ensure_unified_entity(conn, suggestion["raw_name"], body.targetOrgId, is_confirmed=True)
            conn.commit()
            logger.info(f"Merged provisional org '{suggestion['raw_name']}' -> target_org_id={body.targetOrgId}, entity_id={entity_id}")
        except Exception:
            logger.exception("Failed to create unified_entity for merged org (non-fatal)")
            logger.info(f"Merged provisional org '{suggestion['raw_name']}' -> target_org_id={body.targetOrgId}")
        return {
            "status": "merged",
            "target_org_id": body.targetOrgId,
        }
    finally:
        conn.close()


@router.post("/provisional-orgs/{suggestion_id}/dismiss")
def dismiss_provisional_org(suggestion_id: str):
    """Dismiss a provisional org suggestion."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM provisional_org_suggestions WHERE id = ?",
            (suggestion_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        suggestion = dict(row)
        if suggestion["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Suggestion already {suggestion['status']}"
            )

        # Dismiss all pending with same normalized_name
        norm = suggestion["normalized_name"]
        now = datetime.utcnow().isoformat()
        conn.execute("""
            UPDATE provisional_org_suggestions
            SET status = 'dismissed', resolved_at = ?
            WHERE normalized_name = ? AND status = 'pending'
        """, (now, norm))
        conn.commit()

        logger.info(f"Dismissed provisional org '{suggestion['raw_name']}'")
        return {"status": "dismissed"}
    finally:
        conn.close()

