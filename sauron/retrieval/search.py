"""
sauron/retrieval/search.py

Unified search module — shared function for Search API, prep briefs,
morning email, and future consumers. NOT just an API endpoint.
"""

from __future__ import annotations

import logging
from typing import Optional

from sauron.db.connection import get_connection
from sauron.embeddings.embedder import semantic_search

logger = logging.getLogger(__name__)


def unified_search(query: str, limit: int = 20, filters: dict = None) -> dict:
    """Universal retrieval across contacts, beliefs, and semantic embeddings.

    Parameters
    ----------
    query : str
        Natural-language search query.
    limit : int
        Max results per section.
    filters : dict
        Optional filters:
        - source_type: str or list
        - contact_id: str — scope to a person
        - date_from, date_to: ISO date strings
        - context_classification: str

    Returns
    -------
    dict with keys: query, people, beliefs, evidence, transcripts
    """
    filters = filters or {}
    conn = get_connection()
    try:
        # 1. Contact match
        people = _match_contacts(conn, query)

        # 2. Belief match (also includes beliefs for matched contacts)
        matched_contact_ids = [p["id"] for p in people]
        beliefs = _match_beliefs(conn, query, matched_contact_ids)

        # 3. Semantic search -> split, enrich, group
        evidence, transcripts = _semantic_search_enriched(
            conn, query, limit, filters
        )

        return {
            "query": query,
            "people": people,
            "beliefs": beliefs,
            "evidence": evidence,
            "transcripts": transcripts,
        }
    except Exception:
        logger.exception("unified_search failed for query=%r", query)
        return {
            "query": query,
            "people": [],
            "beliefs": [],
            "evidence": [],
            "transcripts": [],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 1: Contact matching
# ---------------------------------------------------------------------------


def _match_contacts(conn, query: str, limit: int = 5) -> list[dict]:
    """Find contacts matching query by name or aliases."""
    pattern = f"%{query}%"
    rows = conn.execute(
        """
        SELECT
            uc.id,
            uc.canonical_name,
            uc.email,
            CASE WHEN vp.id IS NOT NULL THEN 1 ELSE 0 END AS voice_enrolled,
            (SELECT COUNT(DISTINCT ec.conversation_id)
             FROM event_claims ec
             WHERE ec.speaker_id = uc.id) AS conversation_count,
            (SELECT MAX(c2.captured_at)
             FROM event_claims ec2
             JOIN conversations c2 ON ec2.conversation_id = c2.id
             WHERE ec2.speaker_id = uc.id) AS last_interaction
        FROM unified_contacts uc
        LEFT JOIN voice_profiles vp ON vp.contact_id = uc.id
        WHERE uc.canonical_name LIKE ? OR uc.aliases LIKE ?
        ORDER BY conversation_count DESC
        LIMIT ?
        """,
        (pattern, pattern, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Step 2: Belief matching
# ---------------------------------------------------------------------------


def _match_beliefs(
    conn, query: str, contact_ids: list[str], limit: int = 10
) -> list[dict]:
    """Find beliefs matching query text, plus beliefs for matched contacts."""
    pattern = f"%{query}%"

    # Text match on belief_summary and belief_key
    text_rows = conn.execute(
        """
        SELECT b.*, uc.canonical_name AS entity_name
        FROM beliefs b
        LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
        WHERE (b.belief_summary LIKE ? OR b.belief_key LIKE ?)
          AND b.status != 'superseded'
        ORDER BY b.confidence DESC
        LIMIT ?
        """,
        (pattern, pattern, limit),
    ).fetchall()

    results = [dict(r) for r in text_rows]
    seen_ids = {r["id"] for r in results}

    # Also include beliefs for matched contacts
    if contact_ids:
        placeholders = ",".join("?" * len(contact_ids))
        contact_rows = conn.execute(
            f"""
            SELECT b.*, uc.canonical_name AS entity_name
            FROM beliefs b
            LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
            WHERE b.entity_id IN ({placeholders})
              AND b.status != 'superseded'
            ORDER BY b.confidence DESC
            LIMIT ?
            """,
            (*contact_ids, limit),
        ).fetchall()
        for r in contact_rows:
            d = dict(r)
            if d["id"] not in seen_ids:
                results.append(d)
                seen_ids.add(d["id"])

    return results[:limit]


# ---------------------------------------------------------------------------
# Step 3: Semantic search with enrichment
# ---------------------------------------------------------------------------

_EVIDENCE_TYPES = frozenset(
    {"claim", "episode", "extraction_summary", "commitment", "follow_up", "belief"}
)


def _semantic_search_enriched(
    conn, query: str, limit: int, filters: dict
) -> tuple[list[dict], list[dict]]:
    """Run semantic search, split into evidence vs transcripts,
    enrich evidence with source table data, group by conversation."""

    raw = semantic_search(
        query=query,
        limit=limit * 2,
        source_type=filters.get("source_type"),
        contact_id=filters.get("contact_id"),
    )

    evidence_raw = [r for r in raw if r["source_type"] in _EVIDENCE_TYPES]
    transcript_raw = [r for r in raw if r["source_type"] == "transcript_segment"]

    # Enrich evidence items with source table joins
    enriched = _enrich_evidence(conn, evidence_raw)

    # Group by conversation (also fetches conversation metadata)
    grouped = _group_by_conversation(conn, enriched)

    # Apply date filters on groups
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from:
        grouped = [g for g in grouped if (g.get("captured_at") or "") >= date_from]
    if date_to:
        grouped = [g for g in grouped if (g.get("captured_at") or "") <= date_to]

    # Apply context filter
    ctx = filters.get("context_classification")
    if ctx:
        grouped = [g for g in grouped if g.get("context_classification") == ctx]

    # Sort groups by max similarity, limit to 10
    grouped.sort(key=lambda g: g.get("max_similarity", 0), reverse=True)
    grouped = grouped[:10]

    # Transcripts: flat list, fallback only
    enriched_transcripts = _enrich_transcripts(conn, transcript_raw[:5])
    if (
        len(evidence_raw) >= 5
        and filters.get("source_type") != "transcript_segment"
    ):
        enriched_transcripts = []

    return grouped, enriched_transcripts


def _enrich_evidence(conn, evidence_raw: list[dict]) -> list[dict]:
    """Enrich raw semantic results by joining back to source tables."""
    if not evidence_raw:
        return []

    # Collect IDs for batch fetching
    claim_ids = [
        r["source_id"] for r in evidence_raw if r["source_type"] == "claim"
    ]
    episode_ids = [
        r["source_id"] for r in evidence_raw if r["source_type"] == "episode"
    ]

    # Batch fetch claims with episode + speaker joins
    claims_map = {}
    if claim_ids:
        ph = ",".join("?" * len(claim_ids))
        rows = conn.execute(
            f"""
            SELECT ec.*,
                   ee.title        AS episode_title,
                   ee.episode_type AS ep_type,
                   uc.canonical_name AS speaker_name
            FROM event_claims ec
            LEFT JOIN event_episodes ee ON ec.episode_id = ee.id
            LEFT JOIN unified_contacts uc ON ec.speaker_id = uc.id
            WHERE ec.id IN ({ph})
            """,
            claim_ids,
        ).fetchall()
        claims_map = {r["id"]: dict(r) for r in rows}

    # Batch fetch episodes
    episodes_map = {}
    if episode_ids:
        ph = ",".join("?" * len(episode_ids))
        rows = conn.execute(
            f"SELECT * FROM event_episodes WHERE id IN ({ph})",
            episode_ids,
        ).fetchall()
        episodes_map = {r["id"]: dict(r) for r in rows}

    # Build enriched items
    enriched = []
    for r in evidence_raw:
        item = {
            "text": r["text_content"],
            "similarity": r["similarity"],
            "source_type": r["source_type"],
            "source_id": r["source_id"],
            "conversation_id": r["conversation_id"],
            "contact_id": r["contact_id"],
        }

        if r["source_type"] == "claim" and r["source_id"] in claims_map:
            c = claims_map[r["source_id"]]
            item.update({
                "claim_type": c.get("claim_type"),
                "modality": c.get("modality"),
                "confidence": c.get("confidence"),
                "subject_name": c.get("subject_name"),
                "speaker_id": c.get("speaker_id"),
                "speaker_name": c.get("speaker_name"),
                "evidence_quote": c.get("evidence_quote"),
                "episode_id": c.get("episode_id"),
                "episode_title": c.get("episode_title"),
                "episode_type": c.get("ep_type"),
                "claim_text": c.get("claim_text"),
                "importance": c.get("importance"),
                "firmness": c.get("firmness"),
                "direction": c.get("direction"),
                "has_deadline": c.get("has_deadline"),
                "has_condition": c.get("has_condition"),
                "condition_text": c.get("condition_text"),
                "time_horizon": c.get("time_horizon"),
            })

        elif r["source_type"] == "episode" and r["source_id"] in episodes_map:
            ep = episodes_map[r["source_id"]]
            item.update({
                "episode_type": ep.get("episode_type"),
                "title": ep.get("title"),
                "summary": ep.get("summary"),
                "start_time": ep.get("start_time"),
                "end_time": ep.get("end_time"),
            })

        # extraction_summary, commitment, follow_up, belief:
        # text_content from embedding IS the content; no extra join needed.

        enriched.append(item)

    return enriched


def _group_by_conversation(conn, evidence: list[dict]) -> list[dict]:
    """Group evidence items by conversation_id, attach conversation metadata."""
    if not evidence:
        return []

    groups = {}
    for item in evidence:
        cid = item.get("conversation_id")
        if not cid:
            continue
        if cid not in groups:
            groups[cid] = {
                "conversation_id": cid,
                "hits": [],
                "max_similarity": 0,
            }
        groups[cid]["hits"].append(item)
        sim = item.get("similarity", 0)
        if sim > groups[cid]["max_similarity"]:
            groups[cid]["max_similarity"] = sim

    # Batch fetch conversation metadata
    conv_ids = list(groups.keys())
    if conv_ids:
        ph = ",".join("?" * len(conv_ids))
        rows = conn.execute(
            f"""
            SELECT id, captured_at, source, context_classification,
                   title, manual_note
            FROM conversations
            WHERE id IN ({ph})
            """,
            conv_ids,
        ).fetchall()
        for r in rows:
            cid = r["id"]
            if cid in groups:
                groups[cid].update({
                    "captured_at": r["captured_at"],
                    "source": r["source"],
                    "context_classification": r["context_classification"],
                    "label": r["manual_note"] or r["title"] or r["source"],
                })

    # Sort hits within each group by similarity desc
    for g in groups.values():
        g["hits"].sort(key=lambda h: h.get("similarity", 0), reverse=True)

    return list(groups.values())


def _enrich_transcripts(conn, transcript_raw: list[dict]) -> list[dict]:
    """Enrich transcript results with conversation metadata."""
    if not transcript_raw:
        return []

    conv_ids = list(
        {r["conversation_id"] for r in transcript_raw if r.get("conversation_id")}
    )
    conv_map = {}
    if conv_ids:
        ph = ",".join("?" * len(conv_ids))
        rows = conn.execute(
            f"""
            SELECT id, captured_at, source, title, manual_note
            FROM conversations WHERE id IN ({ph})
            """,
            conv_ids,
        ).fetchall()
        conv_map = {r["id"]: dict(r) for r in rows}

    results = []
    for r in transcript_raw:
        conv = conv_map.get(r.get("conversation_id"), {})
        # Try to extract speaker label from text_content (format: "SPEAKER_00: text")
        text = r["text_content"]
        speaker_label = ""
        if ": " in text:
            speaker_label = text.split(": ", 1)[0]
            text = text.split(": ", 1)[1]

        results.append({
            "text": text,
            "speaker_label": speaker_label,
            "similarity": r["similarity"],
            "conversation_id": r["conversation_id"],
            "source_type": r["source_type"],
            "captured_at": conv.get("captured_at"),
            "source": conv.get("source"),
            "label": (
                conv.get("manual_note") or conv.get("title") or conv.get("source")
            ),
        })

    return results
