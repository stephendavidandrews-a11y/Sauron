"""Unified contact resolver — maps speaker identities across systems.

Resolution priority:
1. Anchor speaker (Stephen) via enrolled voice print
2. Calendar match (event attendees)
3. Voice print match (pyannote embedding similarity)
4. Manual resolution (queued for triage)
"""

import json
import logging
import uuid

import numpy as np

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

# Stephen's contact ID — set during enrollment
ANCHOR_CONTACT_ID = None


def resolve_speakers(
    conversation_id: str,
    speaker_embeddings: dict[str, np.ndarray],
    calendar_attendees: list[dict] | None = None,
    conn: "sqlite3.Connection | None" = None,
) -> dict[str, str | None]:
    """Resolve speaker labels to contact IDs.

    Args:
        conversation_id: The conversation being processed.
        speaker_embeddings: Dict of speaker_label -> embedding vector.
        calendar_attendees: Optional list of expected attendees from calendar.

    Returns:
        Dict of speaker_label -> contact_id (or None if unresolved).
    """
    resolved: dict[str, str | None] = {}
    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()

    try:
        # Step 1: Identify anchor speaker (Stephen)
        anchor_id = _get_anchor_contact_id(conn)
        if anchor_id and speaker_embeddings:
            anchor_profile = conn.execute(
                "SELECT mean_embedding FROM voice_profiles WHERE contact_id = ?",
                (anchor_id,),
            ).fetchone()

            if anchor_profile:
                anchor_emb = np.frombuffer(anchor_profile["mean_embedding"], dtype=np.float32)
                best_label = None
                best_sim = -1.0

                for label, emb in speaker_embeddings.items():
                    sim = _cosine_similarity(emb, anchor_emb)
                    if sim > best_sim:
                        best_sim = sim
                        best_label = label

                if best_label and best_sim > 0.70:
                    resolved[best_label] = anchor_id
                    _log_match(conn, conversation_id, best_label, anchor_id,
                               best_sim, "anchor")

        # Step 2: Calendar-based resolution
        if calendar_attendees:
            unresolved_labels = [
                l for l in speaker_embeddings if l not in resolved
            ]
            if len(unresolved_labels) == 1 and len(calendar_attendees) == 1:
                # 1-on-1 with known calendar attendee
                att = calendar_attendees[0]
                contact_id = att.get("matched_contact_id")
                if contact_id:
                    label = unresolved_labels[0]
                    resolved[label] = contact_id
                    _log_match(conn, conversation_id, label, contact_id,
                               0.95, "calendar")

        # Step 3: Voice print matching for remaining speakers
        for label, emb in speaker_embeddings.items():
            if label in resolved:
                continue

            match = _match_voiceprint(conn, emb)
            if match:
                profile_id, contact_id, similarity = match
                if similarity > 0.85:
                    resolved[label] = contact_id
                    _log_match(conn, conversation_id, label, contact_id,
                               similarity, "voiceprint")
                elif similarity > 0.70:
                    # Suggest but don't auto-match — queue for triage
                    resolved[label] = None
                    _log_match(conn, conversation_id, label, contact_id,
                               similarity, "voiceprint_suggest")
                else:
                    resolved[label] = None
                    _log_match(conn, conversation_id, label, None,
                               similarity, "unmatched")
            else:
                resolved[label] = None
                _log_match(conn, conversation_id, label, None,
                           0.0, "unmatched")

        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()

    return resolved


def _get_anchor_contact_id(conn) -> str | None:
    """Get Stephen's contact ID (the anchor speaker)."""
    row = conn.execute(
        "SELECT id FROM unified_contacts WHERE canonical_name = 'Stephen Andrews'"
    ).fetchone()
    return row["id"] if row else None


def _match_voiceprint(conn, embedding: np.ndarray) -> tuple[str, str, float] | None:
    """Find best matching voice profile for an embedding.

    Returns (profile_id, contact_id, similarity) or None.
    """
    profiles = conn.execute(
        "SELECT id, contact_id, mean_embedding FROM voice_profiles WHERE contact_id IS NOT NULL"
    ).fetchall()

    best = None
    best_sim = -1.0

    for profile in profiles:
        stored_emb = np.frombuffer(profile["mean_embedding"], dtype=np.float32)
        emb_norm = np.linalg.norm(stored_emb)
        if np.isnan(emb_norm) or np.isinf(emb_norm) or emb_norm == 0:
            logger.error(
                "CORRUPTED voice profile %s (contact=%s) — "
                "mean_embedding norm=%.4f. Skipping. "
                "Rebuild this profile from voice_samples.",
                profile["id"][:8], profile["contact_id"][:8] if profile["contact_id"] else "None",
                emb_norm if not np.isnan(emb_norm) else float("nan"),
            )
            continue
        sim = _cosine_similarity(embedding, stored_emb)
        if sim > best_sim:
            best_sim = sim
            best = (profile["id"], profile["contact_id"], sim)

    return best if best and best_sim > 0.50 else None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    if a.shape != b.shape:
        return 0.0
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    result = float(np.dot(a, b) / (norm_a * norm_b))
    # Guard against NaN from corrupted embeddings
    if np.isnan(result) or np.isinf(result):
        logger.warning(
            "CORRUPTED EMBEDDING detected in cosine_similarity — "
            "result is %s. Norms: a=%.4f, b=%.4f. "
            "A voice profile may need rebuilding.",
            result, norm_a, norm_b
        )
        return 0.0
    return result


def _log_match(conn, conversation_id, speaker_label, contact_id, similarity, method):
    """Log a speaker match attempt."""
    # Look up profile_id if we have a contact_id
    profile_id = None
    if contact_id:
        row = conn.execute(
            "SELECT id FROM voice_profiles WHERE contact_id = ?", (contact_id,)
        ).fetchone()
        if row:
            profile_id = row["id"]

    conn.execute(
        """INSERT INTO voice_match_log
           (id, conversation_id, speaker_label, matched_profile_id, similarity_score, match_method)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), conversation_id, speaker_label,
         profile_id, similarity, method),
    )
