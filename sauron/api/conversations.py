"""Conversation API endpoints."""

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from sauron.db.connection import get_connection
from sauron.api.entity_helpers import _has_ambiguous_name_ref, replace_confirmed_name, replace_name_in_text
from sauron.pipeline.processor import process_conversation, process_pending

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])


class TranscriptEdit(BaseModel):
    text: str



# ═══════════════════════════════════════════════════════
# LIST ENDPOINTS
# ═══════════════════════════════════════════════════════

@router.get("/needs-review")
def list_needs_review(limit: int = 50):
    """List conversations that are completed but not yet reviewed."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT c.*,
                  (SELECT COUNT(*) FROM event_episodes e WHERE e.conversation_id = c.id) as episode_count,
                  (SELECT COUNT(*) FROM event_claims cl WHERE cl.conversation_id = c.id) as claim_count
               FROM conversations c
               WHERE c.processing_status = 'awaiting_claim_review'
               ORDER BY c.captured_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("")
def list_conversations(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List processed conversations."""
    conn = get_connection()
    try:
        query = """SELECT c.*,
                      (SELECT COUNT(*) FROM event_episodes e WHERE e.conversation_id = c.id) as episode_count,
                      (SELECT COUNT(*) FROM event_claims cl WHERE cl.conversation_id = c.id) as claim_count
                   FROM conversations c"""
        params = []
        if status:
            query += " WHERE c.processing_status = ?"
            params.append(status)
        query += " ORDER BY c.captured_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# CONVERSATION DETAIL
# ═══════════════════════════════════════════════════════


# =====================================================
# QUEUE COUNTS
# =====================================================

@router.get("/queue-counts")
def get_queue_counts():
    """Return counts for each review queue."""
    conn = get_connection()
    try:
        counts = {}
        for status_key, status_val in [
            ("speaker_review", "awaiting_speaker_review"),
            ("triage_review", "triage_rejected"),
            ("claim_review", "awaiting_claim_review"),
        ]:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM conversations WHERE processing_status = ?",
                (status_val,),
            ).fetchone()
            counts[status_key] = row["cnt"]

        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM conversations
               WHERE processing_status IN ('transcribing', 'triaging', 'extracting')""",
        ).fetchone()
        counts["processing"] = row["cnt"]

        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversations WHERE processing_status = 'pending'",
        ).fetchone()
        counts["pending"] = row["cnt"]

        return counts
    finally:
        conn.close()




@router.get("/unreviewed-claims")
def list_unreviewed_claims(limit: int = 50):
    """List unreviewed claims across all awaiting_claim_review conversations.
    Returns a flat list of claims with conversation context, ordered by
    recency then importance.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT ec.*,
                  c.source AS conv_source, c.captured_at AS conv_captured_at,
                  c.manual_note AS conv_manual_note, c.title AS conv_title,
                  c.flagged_for_review AS conv_flagged,
                  ee.title AS episode_title, ee.id AS ep_id
               FROM event_claims ec
               JOIN conversations c ON c.id = ec.conversation_id
               LEFT JOIN event_episodes ee ON ee.id = ec.episode_id
               WHERE c.processing_status = 'awaiting_claim_review'
                 AND ec.review_status = 'unreviewed'
                 AND COALESCE(c.flagged_for_review, 0) = 0
               ORDER BY c.captured_at DESC, ec.importance DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str):
    """Get full conversation details — transcript, extraction, vocal data."""
    conn = get_connection()
    try:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get transcript segments with voice profile info
        segments = conn.execute(
            """SELECT t.*,
                      uc.canonical_name as speaker_name,
                      vp.sample_count as voice_sample_count,
                      vp.confidence_score as voice_confidence
               FROM transcripts t
               LEFT JOIN unified_contacts uc ON t.speaker_id = uc.id
               LEFT JOIN voice_profiles vp ON uc.voice_profile_id = vp.id
               WHERE t.conversation_id = ?
               ORDER BY t.start_time""",
            (conversation_id,),
        ).fetchall()

        # Get extraction
        extraction = conn.execute(
            "SELECT * FROM extractions WHERE conversation_id = ? ORDER BY pass_number DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()

        # Get vocal features
        vocal = conn.execute(
            "SELECT * FROM vocal_features WHERE conversation_id = ? ORDER BY segment_start",
            (conversation_id,),
        ).fetchall()

        # Get episodes (v6)
        episodes = conn.execute(
            "SELECT * FROM event_episodes WHERE conversation_id = ? ORDER BY start_time",
            (conversation_id,),
        ).fetchall()

        # Get claims (v6) — include display_overrides and review_status
        claims = conn.execute(
            """SELECT ec.*, uc.canonical_name as linked_entity_name
               FROM event_claims ec
               LEFT JOIN unified_contacts uc ON ec.subject_entity_id = uc.id
               WHERE ec.conversation_id = ?""",
            (conversation_id,),
        ).fetchall()

        # Get claim_entities junction table data for all claims in this conversation
        # LEFT JOIN unified_entities to get entity_type for non-person entities
        claim_entities_rows = conn.execute(
            """SELECT ce.*, ue.entity_type FROM claim_entities ce
               JOIN event_claims ec ON ce.claim_id = ec.id
               LEFT JOIN unified_entities ue
                 ON ce.entity_id = ue.id AND ce.entity_table = 'unified_entities'
               WHERE ec.conversation_id = ?
               ORDER BY ce.created_at""",
            (conversation_id,),
        ).fetchall()

        # Group claim_entities by claim_id
        claim_entities_by_claim = {}
        for ce in claim_entities_rows:
            ced = dict(ce)
            claim_entities_by_claim.setdefault(ced["claim_id"], []).append(ced)

        # Get belief updates (v6) — beliefs that cite claims from this conversation
        belief_updates = conn.execute(
            """SELECT DISTINCT b.* FROM beliefs b
               JOIN belief_evidence be ON b.id = be.belief_id
               JOIN event_claims ec ON be.claim_id = ec.id
               WHERE ec.conversation_id = ?
               ORDER BY b.last_changed_at DESC""",
            (conversation_id,),
        ).fetchall()

        # Parse extraction extraction_json if available
        extraction_data = None
        if extraction:
            ext_dict = dict(extraction)
            if ext_dict.get("extraction_json"):
                try:
                    extraction_data = json.loads(ext_dict["extraction_json"])
                except (ValueError, TypeError):
                    extraction_data = ext_dict
            else:
                extraction_data = ext_dict

        return {
            "conversation": dict(conv),
            "transcript": [dict(s) for s in segments],
            "extraction": extraction_data,
            "vocal_features": [dict(v) for v in vocal],
            "episodes": [dict(e) for e in episodes],
            "claims": [{**dict(c), "entities": claim_entities_by_claim.get(dict(c)["id"], [])} for c in claims],
            "belief_updates": [dict(b) for b in belief_updates],
        }
    finally:
        conn.close()


# Review lifecycle endpoints extracted to review_actions.py
from sauron.api.review_actions import router as review_router
router.include_router(review_router)


# ═══════════════════════════════════════════════════════
# TRANSCRIPT EDITING
# ═══════════════════════════════════════════════════════

@router.patch("/transcripts/{transcript_id}")
def edit_transcript(transcript_id: str, body: TranscriptEdit):
    """Edit a transcript segment's text. Preserves original Whisper output."""
    conn = get_connection()
    try:
        seg = conn.execute(
            "SELECT * FROM transcripts WHERE id = ?", (transcript_id,)
        ).fetchone()
        if not seg:
            raise HTTPException(status_code=404, detail="Transcript segment not found")

        seg_dict = dict(seg)
        # Save original text if not already saved
        if not seg_dict.get("original_text"):
            conn.execute(
                "UPDATE transcripts SET original_text = text WHERE id = ?",
                (transcript_id,),
            )

        # Update text and mark as corrected
        conn.execute(
            "UPDATE transcripts SET text = ?, user_corrected = 1 WHERE id = ?",
            (body.text, transcript_id),
        )
        conn.commit()
        return {"status": "ok", "transcript_id": transcript_id}
    finally:
        conn.close()


# PROCESSING
# ═══════════════════════════════════════════════════════

@router.post("/process-pending")
def trigger_process_pending():
    """Manually trigger processing of all pending conversations."""
    process_pending()
    return {"status": "ok", "message": "Processing triggered"}


@router.post("/{conversation_id}/reprocess")
def reprocess_conversation(conversation_id: str):
    """Re-run extraction with updated prompt."""
    success = process_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=500, detail="Reprocessing failed")
    return {"status": "ok", "conversation_id": conversation_id}



# =====================================================
# TRANSCRIPT ANNOTATIONS
# =====================================================

class AnnotationCreate(BaseModel):
    conversation_id: str
    transcript_segment_id: str
    start_char: int
    end_char: int
    original_text: str
    resolved_contact_id: str
    resolved_name: str
    annotation_type: str = "name"


@router.get("/{conversation_id}/annotations")
def list_annotations(conversation_id: str):
    """List all transcript annotations for a conversation."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT ta.*, uc.canonical_name as contact_name
               FROM transcript_annotations ta
               LEFT JOIN unified_contacts uc ON ta.resolved_contact_id = uc.id
               WHERE ta.conversation_id = ?
               ORDER BY ta.transcript_segment_id, ta.start_char""",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/annotations")
def create_annotation(body: AnnotationCreate):
    """Create a transcript annotation (link a name/phrase to a contact)."""
    conn = get_connection()
    try:
        ann_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO transcript_annotations
               (id, conversation_id, transcript_segment_id,
                start_char, end_char, original_text,
                resolved_contact_id, resolved_name, annotation_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ann_id, body.conversation_id, body.transcript_segment_id,
             body.start_char, body.end_char, body.original_text,
             body.resolved_contact_id, body.resolved_name, body.annotation_type),
        )
        conn.commit()
        return {"status": "ok", "id": ann_id}
    finally:
        conn.close()


@router.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: str):
    """Delete a transcript annotation."""
    conn = get_connection()
    try:
        result = conn.execute(
            "DELETE FROM transcript_annotations WHERE id = ?",
            (annotation_id,),
        )
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Annotation not found")
        return {"status": "ok", "deleted": annotation_id}
    finally:
        conn.close()


# =====================================================
# SPEAKER MATCH DATA
# =====================================================

@router.get("/{conversation_id}/speaker-matches")
def get_speaker_matches(conversation_id: str):
    """Return voice_match_log entries + manual assignments with contact names for speaker review UI."""
    conn = get_connection()
    try:
        # Voiceprint-based matches (exclude overridden ones)
        rows = conn.execute(
            """SELECT vml.*, vp.display_name as profile_name, uc.canonical_name as contact_name
               FROM voice_match_log vml
               LEFT JOIN voice_profiles vp ON vml.matched_profile_id = vp.id
               LEFT JOIN unified_contacts uc ON vp.contact_id = uc.id
               WHERE vml.conversation_id = ? AND (vml.was_correct IS NULL OR vml.was_correct != 0)
               ORDER BY vml.speaker_label""",
            (conversation_id,),
        ).fetchall()
        results = [dict(r) for r in rows]
        covered_labels = {r["speaker_label"] for r in results}

        # Manual assignments from transcripts (speakers assigned via UI)
        manual_rows = conn.execute(
            """SELECT DISTINCT t.speaker_label, t.speaker_id, uc.canonical_name as contact_name,
                      vp.id as matched_profile_id, vp.display_name as profile_name
               FROM transcripts t
               JOIN unified_contacts uc ON t.speaker_id = uc.id
               LEFT JOIN voice_profiles vp ON vp.contact_id = uc.id
               WHERE t.conversation_id = ? AND t.speaker_id IS NOT NULL""",
            (conversation_id,),
        ).fetchall()

        for mr in manual_rows:
            if mr["speaker_label"] not in covered_labels:
                results.append({
                    "speaker_label": mr["speaker_label"],
                    "contact_name": mr["contact_name"],
                    "profile_name": mr["profile_name"],
                    "matched_profile_id": mr["matched_profile_id"],
                    "match_method": "manual",
                    "similarity_score": 1.0,
                    "was_correct": 1,
                })

        return results
    finally:
        conn.close()


@router.get("/{conversation_id}/triage")
def get_triage_data(conversation_id: str):
    """Return triage extraction data for triage review."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT extraction_json, model_used, input_tokens, output_tokens
               FROM extractions
               WHERE conversation_id = ? AND pass_number = 1
               ORDER BY rowid DESC LIMIT 1""",
            (conversation_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No triage data found")

        triage_data = json.loads(row["extraction_json"])

        episodes = conn.execute(
            "SELECT * FROM event_episodes WHERE conversation_id = ? ORDER BY start_time",
            (conversation_id,),
        ).fetchall()

        return {
            "triage": triage_data,
            "episodes": [dict(e) for e in episodes],
            "model": row["model_used"],
            "tokens": {"input": row["input_tokens"], "output": row["output_tokens"]},
        }
    finally:
        conn.close()

# People endpoints extracted to people_endpoints.py
# People endpoints extracted to people_endpoints.py
from sauron.api.people_endpoints import router as people_router
router.include_router(people_router)

# Routing preview endpoint extracted to routing_preview.py
from sauron.api.routing_preview import router as preview_router
router.include_router(preview_router)
from sauron.api.bulk_reassign import router as bulk_reassign_router
router.include_router(bulk_reassign_router)
