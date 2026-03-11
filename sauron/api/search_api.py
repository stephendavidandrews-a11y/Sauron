"""
sauron/api/search_api.py

API router for semantic search, meeting intentions, and learning amendments.

Endpoints:
  GET  /search                     — semantic search via embedder
  GET  /intentions                 — list recent meeting intentions
  GET  /intentions/{id}            — get specific intention with assessment
  POST /intentions                 — create new intention
  POST /intentions/{id}/link       — link intention to conversation
  POST /intentions/{id}/assess     — assess goals against extraction
  GET  /amendments                 — get active amendment text
  POST /amendments/analyze         — trigger correction analysis
  GET  /amendments/contact/{id}    — get contact extraction preferences
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search-intentions-amendments"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class IntentionCreate(BaseModel):
    goals: list[str]
    concerns: list[str] | None = None
    strategy: str | None = None
    target_contact_id: str | None = None


class IntentionLink(BaseModel):
    conversation_id: str


class IntentionAssess(BaseModel):
    """Optional body — if not provided, we pull the latest extraction
    for the linked conversation automatically."""
    extraction: dict | None = None


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


@router.get("/search")
def search(
    q: str = Query(..., description="Natural-language search query"),
    limit: int = Query(10, ge=1, le=100),
    source_type: Optional[str] = Query(None, description="Filter by source_type"),
    contact_id: Optional[str] = Query(None, description="Filter by contact_id"),
):
    """Semantic search across all embedded content (transcripts, summaries,
    commitments, follow-ups)."""
    try:
        from sauron.embeddings.embedder import semantic_search
        results = semantic_search(
            query=q,
            limit=limit,
            source_type=source_type,
            contact_id=contact_id,
        )
        return {"query": q, "count": len(results), "results": results}
    except Exception as exc:
        logger.exception("Semantic search failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Meeting intentions
# ---------------------------------------------------------------------------


@router.get("/intentions")
def list_intentions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    contact_id: Optional[str] = Query(None),
):
    """List recent meeting intentions, newest first."""
    conn = get_connection()
    try:
        query = "SELECT * FROM meeting_intentions"
        params: list = []
        if contact_id:
            query += " WHERE target_contact_id = ?"
            params.append(contact_id)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            # Parse JSON fields for nicer API output
            for field in ("goals", "concerns", "goals_achieved", "unexpected_outcomes"):
                if d.get(field) and isinstance(d[field], str):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)
        return results
    finally:
        conn.close()


@router.get("/intentions/{intention_id}")
def get_intention(intention_id: str):
    """Get a specific intention with its assessment."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM meeting_intentions WHERE id = ?",
            (intention_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Intention not found")

        d = dict(row)
        # Parse JSON fields
        for field in ("goals", "concerns", "goals_achieved", "unexpected_outcomes"):
            if d.get(field) and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass

        # Attach contact name if we have a target
        if d.get("target_contact_id"):
            contact = conn.execute(
                "SELECT canonical_name FROM unified_contacts WHERE id = ?",
                (d["target_contact_id"],),
            ).fetchone()
            d["target_contact_name"] = (
                contact["canonical_name"] if contact else None
            )

        return d
    finally:
        conn.close()


@router.post("/intentions")
def create_intention_endpoint(body: IntentionCreate):
    """Create a new meeting intention with optional auto-brief."""
    try:
        from sauron.jobs.intentions import create_intention

        intention_id = create_intention(
            goals=body.goals,
            concerns=body.concerns,
            strategy=body.strategy,
            target_contact_id=body.target_contact_id,
        )

        # Fetch and return the created record
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM meeting_intentions WHERE id = ?",
                (intention_id,),
            ).fetchone()
            d = dict(row) if row else {"id": intention_id}
            for field in ("goals", "concerns"):
                if d.get(field) and isinstance(d[field], str):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return d
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("Failed to create intention")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/intentions/{intention_id}/link")
def link_intention_endpoint(intention_id: str, body: IntentionLink):
    """Link a meeting intention to a conversation."""
    try:
        from sauron.jobs.intentions import link_intention_to_conversation

        link_intention_to_conversation(intention_id, body.conversation_id)
        return {"status": "linked", "intention_id": intention_id,
                "conversation_id": body.conversation_id}
    except Exception as exc:
        logger.exception("Failed to link intention")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/intentions/{intention_id}/assess")
def assess_intention_endpoint(intention_id: str, body: IntentionAssess | None = None):
    """Assess goal achievement for an intention.

    If no extraction is provided in the body, the latest extraction for
    the linked conversation is used automatically.
    """
    try:
        from sauron.jobs.intentions import assess_goals

        extraction = None
        if body and body.extraction:
            extraction = body.extraction
        else:
            # Pull from linked conversation
            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT conversation_id FROM meeting_intentions WHERE id = ?",
                    (intention_id,),
                ).fetchone()
                if not row or not row["conversation_id"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Intention has no linked conversation and no extraction provided",
                    )
                ext_row = conn.execute(
                    """
                    SELECT extraction_json FROM extractions
                    WHERE conversation_id = ?
                    ORDER BY pass_number DESC LIMIT 1
                    """,
                    (row["conversation_id"],),
                ).fetchone()
                if not ext_row:
                    raise HTTPException(
                        status_code=400,
                        detail="No extraction found for linked conversation",
                    )
                extraction = json.loads(ext_row["extraction_json"])
            finally:
                conn.close()

        assessment = assess_goals(intention_id, extraction)
        return assessment
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to assess goals")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Learning amendments
# ---------------------------------------------------------------------------


@router.get("/amendments")
def get_active_amendment_endpoint():
    """Get the currently active prompt amendment."""
    try:
        from sauron.learning.amendments import get_active_amendment

        text = get_active_amendment()
        if text is None:
            return {"active": False, "amendment_text": None}
        return {"active": True, "amendment_text": text}
    except Exception as exc:
        logger.exception("Failed to get amendment")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/amendments/analyze")
def analyze_amendments_endpoint():
    """Trigger correction analysis and potentially generate a new amendment."""
    try:
        from sauron.learning.amendments import analyze_corrections_and_amend

        result = analyze_corrections_and_amend()
        if result is None:
            return {
                "status": "no_action",
                "message": "Insufficient corrections to generate a new amendment",
            }
        return {
            "status": "generated",
            "amendment_text": result,
        }
    except Exception as exc:
        logger.exception("Failed to analyze corrections")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/amendments/contact/{contact_id}")
def get_contact_preferences_endpoint(contact_id: str):
    """Get extraction preferences for a specific contact."""
    try:
        from sauron.learning.amendments import get_contact_preferences

        prefs = get_contact_preferences(contact_id)
        if prefs is None:
            raise HTTPException(
                status_code=404,
                detail=f"No preferences found for contact {contact_id}",
            )
        return prefs
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get contact preferences")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Unified search (v2 — retrieval module)
# ---------------------------------------------------------------------------


class SearchEventLog(BaseModel):
    query: str
    query_type: str | None = None
    sections_returned: str | None = None
    result_count: int | None = None
    result_clicked: str | None = None
    time_to_click_ms: int | None = None
    reformulated: bool = False
    session_id: str | None = None


@router.get("/search/unified")
def unified_search_endpoint(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    contact_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    context: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
):
    """Unified search across contacts, beliefs, and semantic embeddings."""
    try:
        from sauron.retrieval.search import unified_search

        filters = {}
        if contact_id:
            filters["contact_id"] = contact_id
        if date_from:
            filters["date_from"] = date_from
        if date_to:
            filters["date_to"] = date_to
        if context:
            filters["context_classification"] = context
        if source_type:
            filters["source_type"] = source_type

        return unified_search(query=q, limit=limit, filters=filters)
    except Exception as exc:
        logger.exception("Unified search failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/search/log")
def log_search_event(body: SearchEventLog):
    """Log a search interaction for telemetry."""
    try:
        import uuid as _uuid
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO search_events
                    (id, query, query_type, sections_returned, result_count,
                     result_clicked, time_to_click_ms, reformulated, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(_uuid.uuid4()),
                    body.query,
                    body.query_type,
                    body.sections_returned,
                    body.result_count,
                    body.result_clicked,
                    body.time_to_click_ms,
                    body.reformulated,
                    body.session_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("Failed to log search event: %s", exc)
        return {"status": "ok"}  # Don't fail the client
