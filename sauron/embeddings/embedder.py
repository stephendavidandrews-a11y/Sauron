"""
sauron/embeddings/embedder.py

Semantic embedding pipeline using sentence-transformers/all-MiniLM-L6-v2.
Stores 384-dim float32 vectors as raw bytes blobs in SQLite.
Brute-force cosine similarity search (sufficient for <100k vectors).

FIXED: transcripts has speaker_label, not speaker.
  - SELECT id, speaker, text -> SELECT id, speaker_label, text
"""

from __future__ import annotations

import json
import logging
import os
import struct
from typing import Optional

# Set HF cache to a writable location before importing sentence_transformers
os.environ.setdefault("HF_HOME", os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "huggingface"
))

import numpy as np
from sentence_transformers import SentenceTransformer

from sauron.config import EMBEDDING_MODEL, EMBEDDING_DIM
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton model loader
# ---------------------------------------------------------------------------

_model: Optional[SentenceTransformer] = None


def _get_model() -> SentenceTransformer:
    """Lazily load the sentence-transformer model exactly once."""
    global _model
    if _model is None:
        logger.info("Loading embedding model %s ...", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("Embedding model loaded (dim=%d).", EMBEDDING_DIM)
    return _model


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def embed_text(text: str) -> bytes:
    """Encode *text* into a 384-dim float32 vector and return raw bytes for
    SQLite BLOB storage."""
    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    # Ensure we get the expected dimensionality
    vector = np.asarray(vector, dtype=np.float32).flatten()
    if vector.shape[0] != EMBEDDING_DIM:
        raise ValueError(
            f"Expected {EMBEDDING_DIM}-dim vector, got {vector.shape[0]}"
        )
    return vector.tobytes()


def _bytes_to_vector(blob: bytes) -> np.ndarray:
    """Deserialise a BLOB back to a numpy float32 array."""
    return np.frombuffer(blob, dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors (assumes unit-normalised)."""
    dot = np.dot(a, b)
    # Defensive — vectors *should* already be normalised, but clamp anyway.
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _already_embedded(
    conn, conversation_id: str, source_type: str, source_id: str
) -> bool:
    """Return True if an embedding row already exists for this source."""
    row = conn.execute(
        """
        SELECT 1 FROM embeddings
        WHERE conversation_id = ? AND source_type = ? AND source_id = ?
        LIMIT 1
        """,
        (conversation_id, source_type, source_id),
    ).fetchone()
    return row is not None


def _store_embedding(
    conn,
    conversation_id: str,
    source_type: str,
    source_id: str,
    text_content: str,
    embedding_blob: bytes,
    contact_id: Optional[str] = None,
) -> None:
    """Insert one embedding row."""
    conn.execute(
        """
        INSERT INTO embeddings
            (conversation_id, source_type, source_id, text_content,
             embedding, contact_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            source_type,
            source_id,
            text_content,
            embedding_blob,
            contact_id,
        ),
    )


# ---------------------------------------------------------------------------
# High-level: embed an entire conversation
# ---------------------------------------------------------------------------


def embed_conversation(conversation_id: str) -> None:
    """Embed all relevant artefacts from a processed conversation.

    Embeds:
    - Each transcript segment  (source_type='transcript_segment')
    - The conversation summary  (source_type='extraction_summary')
    - Each commitment            (source_type='commitment')
    - Each follow-up             (source_type='follow_up')

    Skips items that have already been embedded (idempotent).
    """
    conn = get_connection()
    embedded_count = 0

    # ------------------------------------------------------------------
    # 1. Transcript segments
    #    FIXED: column is speaker_label, not speaker
    # ------------------------------------------------------------------
    segments = conn.execute(
        """
        SELECT id, speaker_label, text FROM transcripts
        WHERE conversation_id = ?
        ORDER BY start_time
        """,
        (conversation_id,),
    ).fetchall()

    for seg in segments:
        seg_id = str(seg["id"])
        if _already_embedded(conn, conversation_id, "transcript_segment", seg_id):
            continue
        text = f'{seg["speaker_label"]}: {seg["text"]}'
        blob = embed_text(text)
        _store_embedding(
            conn, conversation_id, "transcript_segment", seg_id, text, blob
        )
        embedded_count += 1

    # ------------------------------------------------------------------
    # 2. Extraction summary + commitments + follow-ups
    # ------------------------------------------------------------------
    extractions = conn.execute(
        """
        SELECT id, extraction_json FROM extractions
        WHERE conversation_id = ?
        ORDER BY pass_number DESC
        """,
        (conversation_id,),
    ).fetchall()

    for ext in extractions:
        ext_id = str(ext["id"])

        try:
            data = json.loads(ext["extraction_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Skipping malformed extraction_json for extraction %s", ext_id
            )
            continue

        # --- summary ---
        summary = data.get("summary") or data.get("conversation_summary") or ""
        if summary:
            src_id = f"{ext_id}_summary"
            if not _already_embedded(conn, conversation_id, "extraction_summary", src_id):
                blob = embed_text(summary)
                _store_embedding(
                    conn,
                    conversation_id,
                    "extraction_summary",
                    src_id,
                    summary,
                    blob,
                )
                embedded_count += 1

        # --- commitments (my_commitments + contact_commitments) ---
        all_commitments = []
        for key in ("my_commitments", "contact_commitments", "commitments"):
            items = data.get(key)
            if isinstance(items, list):
                all_commitments.extend(items)

        for idx, item in enumerate(all_commitments):
            text = item if isinstance(item, str) else (
                item.get("description") or item.get("text") or json.dumps(item)
            )
            src_id = f"{ext_id}_commitment_{idx}"
            if _already_embedded(conn, conversation_id, "commitment", src_id):
                continue
            contact_id = item.get("contact_id") if isinstance(item, dict) else None
            blob = embed_text(text)
            _store_embedding(
                conn, conversation_id, "commitment", src_id, text, blob, contact_id
            )
            embedded_count += 1

        # --- follow-ups ---
        follow_ups = data.get("follow_ups") or data.get("follow_up_items") or []
        if isinstance(follow_ups, list):
            for idx, item in enumerate(follow_ups):
                text = item if isinstance(item, str) else (
                    item.get("description") or item.get("text") or json.dumps(item)
                )
                src_id = f"{ext_id}_follow_up_{idx}"
                if _already_embedded(conn, conversation_id, "follow_up", src_id):
                    continue
                contact_id = (
                    item.get("contact_id") if isinstance(item, dict) else None
                )
                blob = embed_text(text)
                _store_embedding(
                    conn,
                    conversation_id,
                    "follow_up",
                    src_id,
                    text,
                    blob,
                    contact_id,
                )
                embedded_count += 1


    # ------------------------------------------------------------------
    # 3. Episodes (from event_episodes table)
    # ------------------------------------------------------------------
    episodes = conn.execute(
        """
        SELECT id, title, episode_type, summary FROM event_episodes
        WHERE conversation_id = ?
        ORDER BY start_time
        """,
        (conversation_id,),
    ).fetchall()

    for ep in episodes:
        ep_id = str(ep["id"])
        if _already_embedded(conn, conversation_id, "episode", ep_id):
            continue
        text = f'{ep["episode_type"]}: {ep["title"]} — {ep["summary"]}'
        blob = embed_text(text)
        _store_embedding(conn, conversation_id, "episode", ep_id, text, blob)
        embedded_count += 1

    # ------------------------------------------------------------------
    # 4. Claims (from event_claims table)
    # ------------------------------------------------------------------
    claims_rows = conn.execute(
        """
        SELECT id, claim_type, claim_text, subject_name, target_entity,
               speaker_id
        FROM event_claims
        WHERE conversation_id = ?
        """,
        (conversation_id,),
    ).fetchall()

    for claim in claims_rows:
        claim_id = str(claim["id"])
        if _already_embedded(conn, conversation_id, "claim", claim_id):
            continue
        parts = [f'{claim["claim_type"]}: {claim["claim_text"]}']
        if claim["subject_name"]:
            parts.append(f'(about {claim["subject_name"]})')
        if claim["target_entity"]:
            parts.append(f'(re: {claim["target_entity"]})')
        text = " ".join(parts)
        blob = embed_text(text)
        _store_embedding(
            conn, conversation_id, "claim", claim_id, text, blob,
            contact_id=claim["speaker_id"]
        )
        embedded_count += 1

    # ------------------------------------------------------------------
    # 5. Beliefs linked to this conversation's claims
    # ------------------------------------------------------------------
    belief_rows = conn.execute("""
        SELECT DISTINCT b.id, b.belief_summary, b.entity_type, b.entity_id, b.status
        FROM beliefs b
        JOIN belief_evidence be ON be.belief_id = b.id
        JOIN event_claims ec ON be.claim_id = ec.id
        WHERE ec.conversation_id = ?
    """, (conversation_id,)).fetchall()

    for belief in belief_rows:
        belief_id = str(belief["id"])
        if _already_embedded(conn, conversation_id, "belief", belief_id):
            continue
        text = f'belief ({belief["entity_type"]}): {belief["belief_summary"]}'
        blob = embed_text(text)
        _store_embedding(conn, conversation_id, "belief", belief_id, text, blob,
                         contact_id=belief["entity_id"])
        embedded_count += 1

    conn.commit()
    logger.info(
        "Embedded %d items for conversation %s", embedded_count, conversation_id
    )


# ---------------------------------------------------------------------------
# Semantic search (brute-force cosine similarity)
# ---------------------------------------------------------------------------


def semantic_search(
    query: str,
    limit: int = 10,
    source_type: Optional[str] = None,
    contact_id: Optional[str] = None,
) -> list[dict]:
    """Search the embeddings table by cosine similarity.

    Parameters
    ----------
    query : str
        Natural-language search query.
    limit : int
        Max results to return (default 10).
    source_type : str | None
        Filter by source_type ('transcript_segment', 'extraction_summary',
        'commitment', 'follow_up').
    contact_id : str | None
        Filter to items associated with a specific contact.

    Returns
    -------
    list[dict]
        Each dict has: text_content, similarity, conversation_id, contact_id,
        source_type, source_id.
    """
    query_vec = _bytes_to_vector(embed_text(query))

    conn = get_connection()
    try:
        # Build dynamic WHERE clause
        conditions: list[str] = []
        params: list = []
        if source_type is not None:
            conditions.append("source_type = ?")
            params.append(source_type)
        if contact_id is not None:
            conditions.append("contact_id = ?")
            params.append(contact_id)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        rows = conn.execute(
            f"""
            SELECT id, conversation_id, source_type, source_id,
                   text_content, embedding, contact_id
            FROM embeddings
            {where}
            """,
            params,
        ).fetchall()

        # Score every row
        scored: list[tuple[float, dict]] = []
        for row in rows:
            row_vec = _bytes_to_vector(row["embedding"])
            sim = _cosine_similarity(query_vec, row_vec)
            scored.append(
                (
                    sim,
                    {
                        "text_content": row["text_content"],
                        "similarity": round(sim, 4),
                        "conversation_id": row["conversation_id"],
                        "contact_id": row["contact_id"],
                        "source_type": row["source_type"],
                        "source_id": row["source_id"],
                    },
                )
            )

        # Sort descending by similarity, return top-N
        scored.sort(key=lambda t: t[0], reverse=True)
        return [item for _, item in scored[:limit]]
    finally:
        conn.close()



# ---------------------------------------------------------------------------
# Standalone belief embedder (for backfill)
# ---------------------------------------------------------------------------


def embed_all_beliefs() -> int:
    """Embed all beliefs that haven't been embedded yet. For backfill."""
    conn = get_connection()
    embedded_count = 0

    try:
        beliefs = conn.execute(
            "SELECT id, belief_summary, entity_type, entity_id, status FROM beliefs"
        ).fetchall()

        for belief in beliefs:
            belief_id = str(belief["id"])
            # Use conversation_id=None, source_type='belief_standalone'
            row = conn.execute(
                """
                SELECT 1 FROM embeddings
                WHERE source_type = 'belief_standalone' AND source_id = ?
                LIMIT 1
                """,
                (belief_id,),
            ).fetchone()
            if row:
                continue

            text = f'belief ({belief["entity_type"]}): {belief["belief_summary"]}'
            blob = embed_text(text)
            conn.execute(
                """
                INSERT INTO embeddings
                    (conversation_id, source_type, source_id, text_content,
                     embedding, contact_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    None,
                    "belief_standalone",
                    belief_id,
                    text,
                    blob,
                    belief["entity_id"],
                ),
            )
            embedded_count += 1

        conn.commit()
        logger.info("Embedded %d standalone beliefs", embedded_count)
    finally:
        conn.close()

    return embedded_count


def re_embed_items(items: list[dict]) -> int:
    """Re-embed specific items after text changes (e.g., contact rename).

    Each item: {source_type, source_id, conversation_id, new_text, contact_id}
    Deletes old embedding and inserts new one. Returns count re-embedded.
    """
    from sauron.db.connection import get_connection
    conn = get_connection()
    count = 0
    try:
        for item in items:
            conn.execute(
                "DELETE FROM embeddings WHERE source_type = ? AND source_id = ?",
                (item["source_type"], item["source_id"]),
            )
            blob = embed_text(item["new_text"])
            conn.execute(
                """INSERT INTO embeddings
                    (conversation_id, source_type, source_id, text_content,
                     embedding, contact_id)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    item.get("conversation_id"),
                    item["source_type"],
                    item["source_id"],
                    item["new_text"],
                    blob,
                    item.get("contact_id"),
                ),
            )
            count += 1
        conn.commit()
        logger.info("Re-embedded %d items", count)
    except Exception:
        logger.exception("Re-embed failed")
        conn.rollback()
    finally:
        conn.close()
    return count
