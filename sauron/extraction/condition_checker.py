"""Condition checker — detects when conditional commitment triggers are met.

After extracting claims from a new cluster, this module checks whether any
new facts/events satisfy the conditions on existing conditional commitments.

Flow:
1. Query all conditional commitments from event_claims (date_confidence = 'conditional')
2. For each, semantic-search the new claims against the condition_trigger text
3. If similarity exceeds threshold, create a condition_match record
4. Surface matches in review UI for human approval
5. On approval: upgrade date_confidence, set due_date if resolvable

Tables used:
- event_claims: source of conditional commitments + new claims
- condition_matches: stores detected matches for review
- embeddings: for semantic search (via embedder.py)

The condition_matches table must be created via migrate_db() or init_db().
"""

import json
import logging
import sqlite3

from sauron.db.connection import get_connection as _db_conn
import uuid
from datetime import datetime, timezone

from sauron.config import DB_PATH
from sauron.embeddings.embedder import embed_text, _bytes_to_vector, _cosine_similarity

logger = logging.getLogger(__name__)

# Similarity threshold for flagging a condition match
CONDITION_MATCH_THRESHOLD = 0.70

# Minimum threshold to even consider (below this, skip entirely)
CONDITION_MATCH_FLOOR = 0.55


def ensure_condition_matches_table(conn: sqlite3.Connection) -> None:
    """Create condition_matches table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS condition_matches (
            id TEXT PRIMARY KEY,
            conditional_claim_id TEXT NOT NULL,
            matching_claim_id TEXT NOT NULL,
            matching_conversation_id TEXT,
            similarity REAL NOT NULL,
            condition_trigger TEXT,
            matching_claim_text TEXT,
            status TEXT DEFAULT 'pending',
            resolved_due_date TEXT,
            reviewer_notes TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            FOREIGN KEY (conditional_claim_id) REFERENCES event_claims(id),
            FOREIGN KEY (matching_claim_id) REFERENCES event_claims(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_condition_matches_status
        ON condition_matches(status)
    """)
    conn.commit()


def check_conditions(
    new_claims: list[dict],
    conversation_id: str | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Check whether any new claims satisfy conditions on existing conditional commitments.

    Args:
        new_claims: List of claim dicts just extracted (must have 'id', 'claim_text',
                    'claim_type' fields at minimum)
        conversation_id: The conversation these claims came from
        db_path: Optional DB path override

    Returns:
        List of match dicts: {conditional_claim_id, matching_claim_id, similarity,
                             condition_trigger, matching_claim_text, status}
    """
    if db_path:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
    else:
        conn = _db_conn()

    try:
        ensure_condition_matches_table(conn)

        # 1. Get all conditional commitments
        # date_confidence and condition_trigger are direct columns on event_claims
        conditional_claims = conn.execute("""
            SELECT id, claim_text, condition_trigger, conversation_id,
                   subject_name, speaker_id
            FROM event_claims
            WHERE claim_type = 'commitment'
              AND date_confidence = 'conditional'
              AND condition_trigger IS NOT NULL
        """).fetchall()

        if not conditional_claims:
            logger.debug("No conditional commitments found in DB")
            return []

        logger.info(
            "Checking %d new claims against %d conditional commitments",
            len(new_claims), len(conditional_claims),
        )

        # 2. Embed new claims for comparison
        new_claim_embeddings = {}
        for claim in new_claims:
            claim_id = claim.get("id", "")
            claim_text = claim.get("claim_text", "")
            if claim_text:
                try:
                    vec = _bytes_to_vector(embed_text(claim_text))
                    new_claim_embeddings[claim_id] = {
                        "vector": vec,
                        "text": claim_text,
                        "type": claim.get("claim_type", ""),
                    }
                except Exception as e:
                    logger.warning("Failed to embed claim %s: %s", claim_id, e)

        if not new_claim_embeddings:
            logger.debug("No new claims could be embedded")
            return []

        # 3. For each conditional commitment, check similarity against new claims
        matches = []

        for cond in conditional_claims:
            condition_trigger = cond["condition_trigger"]
            cond_id = cond["id"]

            # Skip if this conditional claim is from the same conversation
            # (don't match a commitment against its own extraction)
            if conversation_id and cond["conversation_id"] == conversation_id:
                continue

            # Embed the condition trigger
            try:
                trigger_vec = _bytes_to_vector(embed_text(condition_trigger))
            except Exception as e:
                logger.warning("Failed to embed condition trigger for %s: %s", cond_id, e)
                continue

            # Check each new claim
            best_match = None
            best_sim = CONDITION_MATCH_FLOOR

            for claim_id, claim_data in new_claim_embeddings.items():
                sim = _cosine_similarity(trigger_vec, claim_data["vector"])

                if sim > best_sim:
                    best_sim = sim
                    best_match = {
                        "claim_id": claim_id,
                        "claim_text": claim_data["text"],
                        "claim_type": claim_data["type"],
                        "similarity": round(sim, 4),
                    }

            if best_match and best_sim >= CONDITION_MATCH_THRESHOLD:
                match_id = str(uuid.uuid4())[:8]

                match_record = {
                    "id": f"cm_{match_id}",
                    "conditional_claim_id": cond_id,
                    "matching_claim_id": best_match["claim_id"],
                    "matching_conversation_id": conversation_id,
                    "similarity": best_match["similarity"],
                    "condition_trigger": condition_trigger,
                    "matching_claim_text": best_match["claim_text"],
                    "status": "pending",
                }

                # Check for existing match (avoid duplicates)
                existing = conn.execute("""
                    SELECT id FROM condition_matches
                    WHERE conditional_claim_id = ?
                      AND matching_claim_id = ?
                """, (cond_id, best_match["claim_id"])).fetchone()

                if not existing:
                    conn.execute("""
                        INSERT INTO condition_matches
                            (id, conditional_claim_id, matching_claim_id,
                             matching_conversation_id, similarity,
                             condition_trigger, matching_claim_text,
                             status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        match_record["id"],
                        cond_id,
                        best_match["claim_id"],
                        conversation_id,
                        best_match["similarity"],
                        condition_trigger,
                        best_match["claim_text"],
                        "pending",
                        datetime.now(timezone.utc).isoformat(),
                    ))
                    conn.commit()

                    logger.info(
                        "Condition match found: %s (sim=%.3f) — "
                        "trigger='%s' matched by '%s'",
                        match_record["id"],
                        best_match["similarity"],
                        condition_trigger[:60],
                        best_match["claim_text"][:60],
                    )

                    matches.append(match_record)

            elif best_match and best_sim >= CONDITION_MATCH_FLOOR:
                logger.debug(
                    "Near-miss condition match (sim=%.3f < %.2f threshold): "
                    "trigger='%s' vs '%s'",
                    best_sim, CONDITION_MATCH_THRESHOLD,
                    condition_trigger[:50],
                    best_match["claim_text"][:50],
                )

        return matches

    finally:
        conn.close()


def resolve_condition_match(
    match_id: str,
    approved: bool,
    due_date: str | None = None,
    reviewer_notes: str | None = None,
    db_path: str | None = None,
) -> dict:
    """Resolve a pending condition match from the review UI.

    Args:
        match_id: condition_matches.id
        approved: True to upgrade the conditional commitment, False to dismiss
        due_date: Optional YYYY-MM-DD to set on the commitment
        reviewer_notes: Optional notes
        db_path: Optional DB path override

    Returns:
        dict with resolution details
    """
    if db_path:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
    else:
        conn = _db_conn()

    try:
        match = conn.execute(
            "SELECT * FROM condition_matches WHERE id = ?", (match_id,)
        ).fetchone()

        if not match:
            return {"error": f"Match {match_id} not found"}

        now = datetime.now(timezone.utc).isoformat()

        if approved:
            # Upgrade the conditional commitment's direct columns
            cond_claim_id = match["conditional_claim_id"]

            new_confidence = "exact" if due_date else "approximate"
            resolution_note = f"Condition resolved at {now} by claim {match['matching_claim_id']}"

            if due_date:
                conn.execute("""
                    UPDATE event_claims
                    SET date_confidence = ?, due_date = ?, date_note = ?
                    WHERE id = ?
                """, (new_confidence, due_date, resolution_note, cond_claim_id))
            else:
                conn.execute("""
                    UPDATE event_claims
                    SET date_confidence = ?, date_note = ?
                    WHERE id = ?
                """, (new_confidence, resolution_note, cond_claim_id))

            # Update match status
            conn.execute("""
                UPDATE condition_matches
                SET status = 'approved', resolved_due_date = ?,
                    reviewer_notes = ?, reviewed_at = ?
                WHERE id = ?
            """, (due_date, reviewer_notes, now, match_id))

            conn.commit()

            logger.info(
                "Condition match %s approved — commitment %s upgraded, due_date=%s",
                match_id, cond_claim_id, due_date,
            )

            return {
                "status": "approved",
                "commitment_id": cond_claim_id,
                "due_date": due_date,
                "message": "Commitment upgraded from conditional",
            }

        else:
            # Dismiss the match
            conn.execute("""
                UPDATE condition_matches
                SET status = 'dismissed', reviewer_notes = ?, reviewed_at = ?
                WHERE id = ?
            """, (reviewer_notes, now, match_id))
            conn.commit()

            logger.info("Condition match %s dismissed", match_id)
            return {"status": "dismissed", "match_id": match_id}

    finally:
        conn.close()


def get_pending_condition_matches(db_path: str | None = None) -> list[dict]:
    """Get all pending condition matches for the review UI.

    Returns:
        List of dicts with match details + the original commitment context
    """
    if db_path:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
    else:
        conn = _db_conn()

    try:
        ensure_condition_matches_table(conn)

        rows = conn.execute("""
            SELECT cm.*,
                   ec.claim_text as commitment_text,
                   ec.subject_name as commitment_subject,
                   ec.speaker_id as commitment_speaker
            FROM condition_matches cm
            LEFT JOIN event_claims ec ON cm.conditional_claim_id = ec.id
            WHERE cm.status = 'pending'
            ORDER BY cm.similarity DESC
        """).fetchall()

        return [dict(r) for r in rows]

    finally:
        conn.close()
