"""Speaker correction, voice enrollment, belief correction, and legacy endpoints."""
import logging
import uuid

import numpy as np
from fastapi import APIRouter, HTTPException

from sauron.db.connection import get_connection
from sauron.api.entity_helpers import replace_name_in_text
from sauron.api.corrections.models import (
    ERROR_TYPES,
    SpeakerCorrection, BeliefCorrection, ExtractionCorrection,
    MergeSpeakersRequest, ReassignSegmentRequest,
)
from sauron.api.corrections.helpers import sync_claim_entities_subject

logger = logging.getLogger(__name__)
router = APIRouter()


def _cascade_speaker_to_claims(conn, conversation_id: str, speaker_label: str, contact_id: str) -> dict:
    """Cascade a confirmed speaker identity to related claims.

    Step 0: Build set of names extraction used for this speaker.
    Step 1: Auto-link unlinked claims attributed to this speaker.
    Step 2: Reassign claims wrongly auto-resolved to a different contact.

    Returns dict with counts: {step1_linked, step2_reassigned}
    """
    stats = {"step1_linked": 0, "step2_reassigned": 0}

    # Look up confirmed contact's canonical name
    contact = conn.execute(
        "SELECT canonical_name FROM unified_contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()
    if not contact:
        return stats
    canonical = contact["canonical_name"]

    # ── Step 0: Build the set of names extraction used for this speaker ──
    speaker_name_rows = conn.execute(
        "SELECT DISTINCT subject_name FROM event_claims WHERE conversation_id = ? AND speaker_id = ?",
        (conversation_id, speaker_label),
    ).fetchall()
    speaker_names = {r["subject_name"].strip().lower() for r in speaker_name_rows if r["subject_name"]}
    # Always include the raw label itself
    speaker_names.add(speaker_label.lower())

    # ── Step 1: Auto-link unlinked claims attributed to this speaker ──
    unlinked = conn.execute(
        """SELECT id, subject_name, claim_text FROM event_claims
           WHERE conversation_id = ?
             AND (subject_name = ? OR speaker_id = ?)
             AND subject_entity_id IS NULL
             AND (review_status IS NULL OR review_status = 'unreviewed')""",
        (conversation_id, speaker_label, speaker_label),
    ).fetchall()

    for claim in unlinked:
        cd = dict(claim)
        subj = (cd["subject_name"] or "").strip()
        # Only process if subject_name is in speaker_names
        if subj.lower() not in speaker_names:
            continue

        # Sync entity link
        sync_claim_entities_subject(conn, cd["id"], contact_id, canonical, "speaker_cascade")

        # Replace name in text
        claim_text = cd["claim_text"] or ""
        if subj and subj != canonical:
            updated = replace_name_in_text(claim_text, subj, canonical)
            if updated and updated != claim_text:
                conn.execute(
                    "UPDATE event_claims SET claim_text = ? WHERE id = ?",
                    (updated, cd["id"]),
                )

        # Log correction event
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, claim_id, error_type, old_value, new_value, correction_source)
               VALUES (?, ?, ?, 'speaker_resolution', ?, ?, 'speaker_cascade')""",
            (str(uuid.uuid4()), conversation_id, cd["id"], subj, canonical),
        )
        stats["step1_linked"] += 1

    # ── Step 2: Reassign wrongly auto-resolved claims ──
    wrongly_resolved = conn.execute(
        """SELECT DISTINCT ec.id, ec.subject_name, ec.claim_text, ec.subject_entity_id,
               uc.canonical_name as wrong_name
           FROM event_claims ec
           JOIN claim_entities ce ON ce.claim_id = ec.id AND ce.role = 'subject'
           JOIN unified_contacts uc ON uc.id = ec.subject_entity_id
           WHERE ec.conversation_id = ?
             AND ec.subject_entity_id IS NOT NULL
             AND ec.subject_entity_id != ?
             AND ce.link_source IN ('model', 'resolver')
             AND (ec.review_status IS NULL OR ec.review_status = 'unreviewed')""",
        (conversation_id, contact_id),
    ).fetchall()

    for claim in wrongly_resolved:
        cd = dict(claim)
        subj = (cd["subject_name"] or "").strip()

        # Only reassign if subject_name is in speaker_names
        if subj.lower() not in speaker_names:
            continue

        # Check claim_entities for user links — skip if user explicitly linked
        user_link = conn.execute(
            """SELECT 1 FROM claim_entities
               WHERE claim_id = ? AND link_source = 'user' LIMIT 1""",
            (cd["id"],),
        ).fetchone()
        if user_link:
            continue

        wrong_name = cd["wrong_name"]

        # Sync entity link (replaces wrong contact with correct one)
        sync_claim_entities_subject(conn, cd["id"], contact_id, canonical, "speaker_cascade")

        # Replace wrong name in text with correct name
        claim_text = cd["claim_text"] or ""
        if wrong_name and wrong_name != canonical:
            updated = replace_name_in_text(claim_text, wrong_name, canonical)
            if updated and updated != claim_text:
                conn.execute(
                    "UPDATE event_claims SET claim_text = ? WHERE id = ?",
                    (updated, cd["id"]),
                )

        # Log correction event
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, claim_id, error_type, old_value, new_value, correction_source)
               VALUES (?, ?, ?, 'bad_entity_linking', ?, ?, 'speaker_cascade')""",
            (str(uuid.uuid4()), conversation_id, cd["id"], wrong_name, canonical),
        )
        stats["step2_reassigned"] += 1

    if stats["step1_linked"] or stats["step2_reassigned"]:
        logger.info(
            f"Speaker cascade for {speaker_label} -> {canonical}: "
            f"{stats['step1_linked']} auto-linked, {stats['step2_reassigned']} reassigned"
        )

    return stats


def _promote_voice_sample(conn, conversation_id: str, speaker_label: str, contact_id: str):
    """Promote a confirmed speaker embedding into a voice profile.

    Called after speaker correction is confirmed in Review.
    Creates a new voice profile if the contact doesn't have one,
    or updates the existing profile's mean embedding with the new sample.

    Quality gates:
    - Sample must have minimum speech duration (5s)
    - Skip if embedding is missing or zero-length
    """
    # Try labeled sample first (post-migration data)
    labeled_sample = conn.execute(
        """SELECT id, embedding, voice_profile_id, duration_seconds
           FROM voice_samples
           WHERE source_conversation_id = ? AND speaker_label = ?
           ORDER BY created_at LIMIT 1""",
        (conversation_id, speaker_label),
    ).fetchone()

    if not labeled_sample:
        # Fallback: try matching by index (pre-migration data)
        all_samples = conn.execute(
            """SELECT id, embedding, voice_profile_id, duration_seconds
               FROM voice_samples
               WHERE source_conversation_id = ?
                 AND confirmation_method = 'unmatched'
               ORDER BY created_at""",
            (conversation_id,),
        ).fetchall()

        if not all_samples:
            logger.warning(f"No unmatched voice samples for conversation {conversation_id[:8]}")
            return

        # Get speaker labels in order from transcripts
        speaker_labels_ordered = conn.execute(
            """SELECT DISTINCT speaker_label FROM transcripts
               WHERE conversation_id = ? ORDER BY MIN(start_time)""",
            (conversation_id,),
        ).fetchall()
        label_order = [r["speaker_label"] for r in speaker_labels_ordered]

        try:
            label_idx = label_order.index(speaker_label)
            if label_idx < len(all_samples):
                labeled_sample = all_samples[label_idx]
        except (ValueError, IndexError):
            logger.warning(f"Cannot map speaker_label {speaker_label} to a voice sample")
            return

    if not labeled_sample:
        return

    sample_dict = dict(labeled_sample)
    embedding_bytes = sample_dict.get("embedding")

    if not embedding_bytes or len(embedding_bytes) == 0:
        return

    embedding = np.frombuffer(embedding_bytes, dtype=np.float64)
    if np.linalg.norm(embedding) == 0:
        return

    # ── Quality gate: minimum speech duration ──
    speech_duration = conn.execute(
        """SELECT SUM(end_time - start_time) as total
           FROM transcripts
           WHERE conversation_id = ? AND speaker_label = ?""",
        (conversation_id, speaker_label),
    ).fetchone()
    total_speech = speech_duration["total"] if speech_duration and speech_duration["total"] else 0

    if total_speech < 5.0:
        logger.info(
            f"Skipping voice profile update for {speaker_label}: "
            f"only {total_speech:.1f}s of speech (minimum 5s)"
        )
        conn.execute(
            "UPDATE voice_samples SET confirmation_method = 'confirmed_low_quality' WHERE id = ?",
            (sample_dict["id"],),
        )
        return

    # ── Find or create voice profile ──
    existing_profile = conn.execute(
        "SELECT id, mean_embedding, sample_count, confidence_score FROM voice_profiles WHERE contact_id = ?",
        (contact_id,),
    ).fetchone()

    if existing_profile:
        profile = dict(existing_profile)
        profile_id = profile["id"]
        old_mean = np.frombuffer(profile["mean_embedding"], dtype=np.float32)
        old_count = profile["sample_count"] or 0

        # Incremental mean: new_mean = (old_mean * count + new_sample) / (count + 1)
        new_count = old_count + 1
        new_mean = (old_mean * old_count + embedding) / new_count
        # Validate result before storage
        if np.any(np.isnan(new_mean)) or np.any(np.isinf(new_mean)):
            logger.error(
                "VOICE PROFILE CORRUPTION PREVENTED: contact %s — "
                "mean embedding would contain NaN/Inf after adding sample. "
                "old_mean dtype=%s shape=%s, embedding dtype=%s shape=%s. "
                "Profile NOT updated. Manual rebuild needed.",
                contact_id[:8], old_mean.dtype, old_mean.shape,
                embedding.dtype, embedding.shape,
            )
            return
        new_mean = new_mean.astype(np.float32)
        new_confidence = 1.0 - (1.0 / (new_count + 1))

        conn.execute(
            """UPDATE voice_profiles
               SET mean_embedding = ?, sample_count = ?, confidence_score = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (new_mean.tobytes(), new_count, new_confidence, profile_id),
        )
        logger.info(
            f"Updated voice profile for contact {contact_id[:8]}: "
            f"{new_count} samples, confidence {new_confidence:.2f}"
        )
    else:
        # Create new voice profile
        profile_id = str(uuid.uuid4())
        contact_row = conn.execute(
            "SELECT canonical_name FROM unified_contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        display_name = contact_row["canonical_name"] if contact_row else "Unknown"

        conn.execute(
            """INSERT INTO voice_profiles
               (id, contact_id, display_name, mean_embedding, sample_count,
                confidence_score, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, 0.5, datetime('now'), datetime('now'))""",
            (profile_id, contact_id, display_name, embedding.tobytes()),
        )
        conn.execute(
            "UPDATE unified_contacts SET voice_profile_id = ? WHERE id = ?",
            (profile_id, contact_id),
        )
        logger.info(
            f"Created voice profile for {display_name} (contact {contact_id[:8]}): "
            f"profile {profile_id[:8]}, 1 sample"
        )

    # Update the voice sample record
    conn.execute(
        """UPDATE voice_samples
           SET voice_profile_id = ?, confirmation_method = 'user_confirmed'
           WHERE id = ?""",
        (profile_id, sample_dict["id"]),
    )

    # Insert corrected match into voice_match_log so speaker-matches reflects the assignment
    conn.execute(
        """INSERT INTO voice_match_log
           (id, conversation_id, speaker_label, matched_profile_id,
            similarity_score, match_method, was_correct, created_at)
           VALUES (?, ?, ?, ?, 1.0, 'manual', 1, datetime('now'))
        """,
        (str(uuid.uuid4()), conversation_id, speaker_label, profile_id),
    )


@router.post("/speaker")
def correct_speaker(correction: SpeakerCorrection):
    """Correct a speaker identification. Cascades to transcripts, logs event,
    and promotes confirmed embedding into voice profile."""
    conn = get_connection()
    try:
        # Update transcript segments
        conn.execute(
            "UPDATE transcripts SET speaker_id = ? WHERE conversation_id = ? AND speaker_label = ?",
            (correction.correct_contact_id, correction.conversation_id, correction.speaker_label),
        )

        # Log correction event
        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, error_type, old_value, new_value, correction_source)
               VALUES (?, ?, 'speaker_resolution', ?, ?, 'manual_ui')""",
            (event_id, correction.conversation_id,
             correction.speaker_label, correction.correct_contact_id),
        )

        # Update voice match log
        conn.execute(
            "UPDATE voice_match_log SET was_correct = 0 WHERE conversation_id = ? AND speaker_label = ?",
            (correction.conversation_id, correction.speaker_label),
        )

        # NEW: Promote confirmed embedding into voice profile
        _promote_voice_sample(conn, correction.conversation_id,
                              correction.speaker_label, correction.correct_contact_id)

        # ── SPEAKER CASCADE TO CLAIMS ──
        cascade_stats = _cascade_speaker_to_claims(
            conn, correction.conversation_id,
            correction.speaker_label, correction.correct_contact_id
        )

        conn.commit()
        return {"status": "ok", "event_id": event_id, "cascade": cascade_stats}
    finally:
        conn.close()


@router.post("/belief")
def correct_belief(correction: BeliefCorrection):
    """Correct a belief status directly."""
    valid_states = [
        "active", "provisional", "refined", "qualified", "time_bounded",
        "superseded", "contested", "stale", "under_review",
    ]
    if correction.new_status not in valid_states:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid_states}")

    conn = get_connection()
    try:
        old = conn.execute("SELECT status FROM beliefs WHERE id = ?", (correction.belief_id,)).fetchone()
        if not old:
            raise HTTPException(404, "Belief not found")

        conn.execute(
            "UPDATE beliefs SET status = ?, last_changed_at = datetime('now') WHERE id = ?",
            (correction.new_status, correction.belief_id),
        )

        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO correction_events
               (id, belief_id, error_type, old_value, new_value, user_feedback, correction_source)
               VALUES (?, ?, 'bad_belief_synthesis', ?, ?, ?, 'manual_ui')""",
            (event_id, correction.belief_id, old["status"],
             correction.new_status, correction.user_feedback),
        )

        if old["status"] != correction.new_status:
            conn.execute(
                """INSERT INTO belief_transitions
                   (id, belief_id, old_status, new_status, driver, source_correction_id)
                   VALUES (?, ?, ?, ?, 'user_action', ?)""",
                (str(uuid.uuid4()), correction.belief_id, old["status"],
                 correction.new_status, event_id),
            )

        conn.commit()
        return {"status": "ok", "event_id": event_id}
    finally:
        conn.close()


@router.post("/extraction")
def correct_extraction(correction: ExtractionCorrection):
    """Legacy correction endpoint — logs to both tables."""
    conn = get_connection()
    try:
        eid = str(uuid.uuid4())
        error_type = correction.correction_type if correction.correction_type in ERROR_TYPES else "hallucinated_claim"
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, error_type, old_value, new_value, correction_source)
               VALUES (?, ?, ?, ?, ?, 'manual_ui')""",
            (eid, correction.conversation_id, error_type,
             correction.original_value, correction.corrected_value),
        )
        conn.execute(
            """INSERT INTO extraction_corrections
               (id, conversation_id, correction_type, original_value, corrected_value)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), correction.conversation_id,
             correction.correction_type, correction.original_value,
             correction.corrected_value),
        )
        conn.commit()
        return {"status": "ok", "event_id": eid}
    finally:
        conn.close()


@router.post("/merge-speakers")
def merge_speakers(req: MergeSpeakersRequest):
    """Merge two speaker labels in a conversation (pre-extraction).

    Updates all transcripts with from_label to use to_label instead.
    Also updates voice_match_log entries.
    """
    conn = get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transcripts WHERE conversation_id = ? AND speaker_label = ?",
            (req.conversation_id, req.from_label),
        ).fetchone()["cnt"]
        if count == 0:
            raise HTTPException(404, f"No segments with speaker_label '{req.from_label}' in this conversation")

        conn.execute(
            "UPDATE transcripts SET speaker_label = ? WHERE conversation_id = ? AND speaker_label = ?",
            (req.to_label, req.conversation_id, req.from_label),
        )

        conn.execute(
            "UPDATE voice_match_log SET speaker_label = ? WHERE conversation_id = ? AND speaker_label = ?",
            (req.to_label, req.conversation_id, req.from_label),
        )

        conn.commit()

        logger.info(
            f"Merged speakers in {req.conversation_id[:8]}: "
            f"{req.from_label} -> {req.to_label} ({count} segments)"
        )

        return {
            "status": "ok",
            "segments_updated": count,
            "from_label": req.from_label,
            "to_label": req.to_label,
        }
    finally:
        conn.close()


@router.post("/reassign-segment")
def reassign_segment(req: ReassignSegmentRequest):
    """Reassign a single transcript segment to a different speaker label (pre-extraction).

    Unlike correct_speaker which cascades to claims, this only changes the
    transcript segment speaker_label. Used during speaker review before
    any extraction has happened.
    """
    conn = get_connection()
    try:
        seg = conn.execute(
            "SELECT id, speaker_label FROM transcripts WHERE id = ?",
            (req.transcript_segment_id,),
        ).fetchone()
        if not seg:
            raise HTTPException(404, "Transcript segment not found")

        old_label = seg["speaker_label"]
        conn.execute(
            "UPDATE transcripts SET speaker_label = ? WHERE id = ?",
            (req.new_speaker_label, req.transcript_segment_id),
        )
        conn.commit()

        logger.info(
            f"Reassigned segment {req.transcript_segment_id[:8]}: "
            f"{old_label} -> {req.new_speaker_label}"
        )

        return {
            "status": "ok",
            "transcript_segment_id": req.transcript_segment_id,
            "old_label": old_label,
            "new_label": req.new_speaker_label,
        }
    finally:
        conn.close()
