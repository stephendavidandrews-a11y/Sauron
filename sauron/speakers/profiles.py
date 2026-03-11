"""Voice profile management — enrollment, updating, and querying."""

import logging
import uuid

import numpy as np

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


def enroll_speaker(
    contact_id: str,
    display_name: str,
    embedding: np.ndarray,
    conversation_id: str | None = None,
    source_type: str = "manual",
    confirmation_method: str = "manual",
) -> str:
    """Enroll a new speaker with their first voice sample.

    Returns the voice profile ID.
    """
    conn = get_connection()
    try:
        profile_id = str(uuid.uuid4())
        sample_id = str(uuid.uuid4())

        conn.execute(
            """INSERT INTO voice_profiles
               (id, contact_id, display_name, mean_embedding, sample_count, confidence_score)
               VALUES (?, ?, ?, ?, 1, 0.5)""",
            (profile_id, contact_id, display_name, embedding.tobytes()),
        )

        conn.execute(
            """INSERT INTO voice_samples
               (id, voice_profile_id, embedding, source_conversation_id,
                source_type, confirmation_method)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sample_id, profile_id, embedding.tobytes(),
             conversation_id, source_type, confirmation_method),
        )

        # Link profile to unified contact
        conn.execute(
            "UPDATE unified_contacts SET voice_profile_id = ? WHERE id = ?",
            (profile_id, contact_id),
        )

        conn.commit()
        logger.info(f"Enrolled speaker '{display_name}' (profile={profile_id[:8]})")
        return profile_id
    finally:
        conn.close()


def add_sample(
    profile_id: str,
    embedding: np.ndarray,
    conversation_id: str,
    source_type: str,
    confirmation_method: str,
):
    """Add a voice sample to an existing profile and update mean embedding."""
    conn = get_connection()
    try:
        sample_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO voice_samples
               (id, voice_profile_id, embedding, source_conversation_id,
                source_type, confirmation_method)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sample_id, profile_id, embedding.tobytes(),
             conversation_id, source_type, confirmation_method),
        )

        # Recalculate mean embedding from all samples
        samples = conn.execute(
            "SELECT embedding FROM voice_samples WHERE voice_profile_id = ?",
            (profile_id,),
        ).fetchall()

        all_embs = [np.frombuffer(s["embedding"], dtype=np.float32) for s in samples]
        mean_emb = np.mean(all_embs, axis=0)

        conn.execute(
            """UPDATE voice_profiles SET
               mean_embedding = ?, sample_count = ?, confidence_score = ?,
               updated_at = datetime('now')
               WHERE id = ?""",
            (mean_emb.tobytes(), len(all_embs),
             min(1.0, len(all_embs) * 0.15 + 0.25), profile_id),
        )

        conn.commit()
        logger.info(f"Added sample to profile {profile_id[:8]} (total={len(all_embs)})")
    finally:
        conn.close()


def get_profile(profile_id: str) -> dict | None:
    """Get a voice profile by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM voice_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_profiles() -> list[dict]:
    """List all voice profiles."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT vp.id, vp.contact_id, vp.display_name, vp.sample_count,
                      vp.confidence_score, uc.canonical_name
               FROM voice_profiles vp
               LEFT JOIN unified_contacts uc ON uc.voice_profile_id = vp.id
               ORDER BY vp.display_name"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
