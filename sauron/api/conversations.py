"""Conversation API endpoints."""

import json
import logging
import re
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


class BulkReassignRequest(BaseModel):
    from_entity_id: str
    to_entity_id: str
    scope: str = "all"  # "all" | "claims_only" | "transcript_only"
    dry_run: bool = True


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
        claim_entities_rows = conn.execute(
            """SELECT ce.* FROM claim_entities ce
               JOIN event_claims ec ON ce.claim_id = ec.id
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


# ═══════════════════════════════════════════════════════
# REVIEW + ROUTING
# ═══════════════════════════════════════════════════════

@router.patch("/{conversation_id}/flag")
def flag_conversation(conversation_id: str):
    """Flag a conversation for deep review. Removes its claims from Quick Pass."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE conversations SET flagged_for_review = 1 WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
        return {"status": "ok", "conversation_id": conversation_id, "flagged_for_review": True}
    finally:
        conn.close()



@router.patch("/{conversation_id}/discard")
def discard_conversation(conversation_id: str, body: dict = None):
    """Discard a conversation. Terminal status, removes from all review queues.
    Available from speaker_review, triage_rejected, and claim_review stages."""
    conn = get_connection()
    try:
        conv = conn.execute(
            "SELECT processing_status FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        allowed = {"awaiting_speaker_review", "triage_rejected", "awaiting_claim_review"}
        current = conv["processing_status"]
        if current not in allowed:
            raise HTTPException(
                status_code=400,
                detail="Cannot discard from status '%s'. Allowed: %s" % (current, ", ".join(sorted(allowed))),
            )

        reason = (body or {}).get("reason", "user_discarded")

        conn.execute(
            "UPDATE conversations SET processing_status = 'discarded' WHERE id = ?",
            (conversation_id,),
        )

        import uuid as _uuid
        conn.execute(
            "INSERT INTO correction_events (id, conversation_id, error_type, old_value, new_value, correction_source) VALUES (?, ?, 'conversation_discarded', ?, ?, 'manual_ui')",
            (str(_uuid.uuid4()), conversation_id, current, reason),
        )

        conn.commit()
        logger.info("Discarded conversation %s (was %s, reason: %s)", conversation_id[:8], current, reason)
        return {"status": "ok", "conversation_id": conversation_id, "discarded": True}
    finally:
        conn.close()


@router.post("/{conversation_id}/review")
def mark_reviewed(conversation_id: str):
    """Mark a conversation as reviewed and trigger routing to downstream apps."""
    conn = get_connection()
    try:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Set reviewed_at and update status to completed
        conn.execute(
            """UPDATE conversations
               SET reviewed_at = datetime('now'),
                   processing_status = 'completed'
               WHERE id = ?""",
            (conversation_id,),
        )
        conn.commit()

        # Route REVIEWED data (corrected DB state, not stale extraction JSON)
        try:
            from sauron.routing.reviewed_payload import build_reviewed_payload
            from sauron.routing.router import route_extraction
            reviewed_payload = build_reviewed_payload(conversation_id)
            route_extraction(conversation_id, reviewed_payload)

            # Only set routed_at if routing was not held as pending_entity
            # and no failures occurred.
            # IMPORTANT: Use a fresh connection to check routing_log because
            # route_to_networking_app writes failures via its own connection,
            # and the original conn may not see those rows (SQLite read isolation).
            check_conn = get_connection()
            try:
                pending_or_failed = check_conn.execute(
                    """SELECT COUNT(*) as cnt FROM routing_log
                       WHERE conversation_id = ?
                         AND status IN ('pending_entity', 'failed')""",
                    (conversation_id,),
                ).fetchone()
            finally:
                check_conn.close()

            if not pending_or_failed or pending_or_failed["cnt"] == 0:
                conn.execute(
                    "UPDATE conversations SET routed_at = datetime('now') WHERE id = ?",
                    (conversation_id,),
                )
                conn.commit()
                logger.info(f"Routed reviewed conversation {conversation_id[:8]} (authoritative payload)")
            else:
                logger.info(
                    f"Reviewed conversation {conversation_id[:8]} — routing held "
                    f"({pending_or_failed['cnt']} pending/failed entries in routing_log)"
                )
        except Exception:
            logger.exception(f"Routing failed for {conversation_id[:8]} (non-fatal)")

        # Count correction stats for this conversation (Change 5)
        try:
            stats_row = conn.execute(
                """SELECT
                    (SELECT COUNT(*) FROM event_claims WHERE conversation_id = ? AND review_status = 'user_confirmed') as approved,
                    (SELECT COUNT(*) FROM event_claims WHERE conversation_id = ? AND review_status = 'dismissed') as dismissed,
                    (SELECT COUNT(*) FROM correction_events WHERE conversation_id = ?) as corrections,
                    (SELECT COUNT(DISTINCT b.id) FROM beliefs b
                     JOIN belief_evidence be ON be.belief_id = b.id
                     JOIN event_claims ec ON be.claim_id = ec.id
                     WHERE ec.conversation_id = ? AND b.status = 'under_review') as beliefs_affected
                """,
                (conversation_id, conversation_id, conversation_id, conversation_id),
            ).fetchone()
            review_stats = {
                "approved": stats_row["approved"] or 0,
                "dismissed": stats_row["dismissed"] or 0,
                "corrections": stats_row["corrections"] or 0,
                "beliefs_affected": stats_row["beliefs_affected"] or 0,
            }
        except Exception:
            review_stats = None

        return {"status": "ok", "conversation_id": conversation_id, "reviewed": True, "stats": review_stats}
    finally:
        conn.close()


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


# ═══════════════════════════════════════════════════════
# BULK REASSIGNMENT
# ═══════════════════════════════════════════════════════

@router.post("/{conversation_id}/bulk-reassign")
def bulk_reassign(conversation_id: str, req: BulkReassignRequest):
    """Bulk reassign entity references from one contact to another.

    dry_run=True (mandatory first): Returns preview of affected counts + sample diff.
    dry_run=False: Executes the reassignment, logs correction events,
                   flags ambiguous claims, invalidates affected beliefs.
    """
    if req.scope not in ("all", "claims_only", "transcript_only"):
        raise HTTPException(400, f"Invalid scope: {req.scope}")

    conn = get_connection()
    try:
        # Verify conversation exists
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not conv:
            raise HTTPException(404, "Conversation not found")

        # Verify both entities exist
        from_contact = conn.execute(
            "SELECT id, canonical_name FROM unified_contacts WHERE id = ?",
            (req.from_entity_id,),
        ).fetchone()
        if not from_contact:
            raise HTTPException(404, f"Source entity {req.from_entity_id} not found")

        to_contact = conn.execute(
            "SELECT id, canonical_name FROM unified_contacts WHERE id = ?",
            (req.to_entity_id,),
        ).fetchone()
        if not to_contact:
            raise HTTPException(404, f"Target entity {req.to_entity_id} not found")

        from_name = from_contact["canonical_name"]
        to_name = to_contact["canonical_name"]

        # Find affected claims (subject_entity_id matches from_entity)
        affected_claims = []
        if req.scope in ("all", "claims_only"):
            affected_claims = conn.execute(
                """SELECT id, claim_text, subject_entity_id, subject_name,
                          target_entity, speaker_id, claim_type, confidence
                   FROM event_claims
                   WHERE conversation_id = ?
                     AND subject_entity_id = ?""",
                (conversation_id, req.from_entity_id),
            ).fetchall()

        # Find affected transcript segments
        affected_transcripts = []
        if req.scope in ("all", "transcript_only"):
            affected_transcripts = conn.execute(
                """SELECT id, speaker_id, speaker_label, text, start_time
                   FROM transcripts
                   WHERE conversation_id = ?
                     AND speaker_id = ?""",
                (conversation_id, req.from_entity_id),
            ).fetchall()

        # Find affected belief evidence links
        affected_belief_ids = set()
        if affected_claims:
            claim_ids = [dict(c)["id"] for c in affected_claims]
            placeholders = ",".join("?" * len(claim_ids))
            belief_rows = conn.execute(
                f"""SELECT DISTINCT belief_id FROM belief_evidence
                    WHERE claim_id IN ({placeholders})""",
                claim_ids,
            ).fetchall()
            affected_belief_ids = {r["belief_id"] for r in belief_rows}

        # Build sample claims for preview
        sample_claims = []
        for c in affected_claims[:5]:
            cd = dict(c)
            sample_claims.append({
                "id": cd["id"],
                "claim_text": cd["claim_text"],
                "old_subject": cd["subject_name"],
                "new_subject": to_name,
                "claim_type": cd["claim_type"],
            })

        # ═══ DRY RUN: return preview only ═══
        if req.dry_run:
            return {
                "dry_run": True,
                "from_entity": from_name,
                "to_entity": to_name,
                "claims_affected": len(affected_claims),
                "transcript_segments_affected": len(affected_transcripts),
                "belief_evidence_links_affected": len(affected_belief_ids),
                "sample_claims": sample_claims,
            }

        # ═══ EXECUTE MODE ═══

        # 1. Reassign claims
        claims_updated = 0
        ambiguous_claim_ids = []
        learned_alias_names = set()  # Track unique names for alias learning
        for claim in affected_claims:
            cd = dict(claim)
            claim_id = cd["id"]
            old_subject = cd["subject_name"] or ""

            # Update subject_entity_id, subject_name, AND claim_entities junction table
            from sauron.api.corrections import sync_claim_entities_subject
            sync_claim_entities_subject(
                conn, claim_id, req.to_entity_id, to_name, "bulk_reassign"
            )

            # Collect unique subject names for alias learning
            if old_subject and old_subject.strip():
                learned_alias_names.add(old_subject.strip())

            # Log correction event for each claim
            conn.execute(
                """INSERT INTO correction_events
                   (id, conversation_id, claim_id, error_type,
                    old_value, new_value, correction_source)
                   VALUES (?, ?, ?, 'bad_entity_linking', ?, ?, 'bulk_reassign')""",
                (str(uuid.uuid4()), conversation_id, claim_id,
                 old_subject, to_name),
            )

            # Replace name references in claim text
            claim_text = cd["claim_text"] or ""
            # Try direct full-name replacement first (Bug 4 fix)
            direct_result = replace_name_in_text(claim_text, from_name, to_name)
            if direct_result and direct_result != claim_text:
                conn.execute(
                    "UPDATE event_claims SET claim_text = ?, display_overrides = NULL WHERE id = ?",
                    (direct_result, claim_id),
                )
            elif _has_ambiguous_name_ref(claim_text, from_name, to_name):
                # Check for other entities in this claim that share the first name
                other_entities = conn.execute(
                    """SELECT DISTINCT entity_name FROM claim_entities
                       WHERE claim_id = ? AND entity_name != ?""",
                    (claim_id, to_name),
                ).fetchall()
                other_names = [r["entity_name"] for r in other_entities]
                # Also include target_entity if present
                target = cd.get("target_entity")
                if target:
                    other_names.append(target)

                updated_text = replace_confirmed_name(claim_text, to_name, other_names)
                if updated_text is None:
                    # Ambiguous: multiple people with same first name in this claim
                    ambiguous_claim_ids.append(claim_id)
                elif updated_text != claim_text:
                    conn.execute(
                        "UPDATE event_claims SET claim_text = ?, display_overrides = NULL WHERE id = ?",
                        (updated_text, claim_id),
                    )

            claims_updated += 1

        # Learn aliases from unique subject names in reassigned claims
        if learned_alias_names:
            try:
                from sauron.extraction.alias_learner import learn_alias
                for alias_name in learned_alias_names:
                    learn_alias(conn, req.to_entity_id, alias_name, to_name)
            except Exception:
                pass  # Non-fatal

        # 2. Reassign transcript segments
        transcripts_updated = 0
        if req.scope in ("all", "transcript_only"):
            for seg in affected_transcripts:
                sd = dict(seg)
                conn.execute(
                    "UPDATE transcripts SET speaker_id = ? WHERE id = ?",
                    (req.to_entity_id, sd["id"]),
                )
                transcripts_updated += 1

            # Log one correction event for transcript reassignment
            if transcripts_updated > 0:
                conn.execute(
                    """INSERT INTO correction_events
                       (id, conversation_id, error_type, old_value, new_value,
                        correction_source)
                       VALUES (?, ?, 'speaker_resolution', ?, ?, 'bulk_reassign')""",
                    (str(uuid.uuid4()), conversation_id,
                     f"{from_name} ({req.from_entity_id})",
                     f"{to_name} ({req.to_entity_id})"),
                )

        # 3. Invalidate affected beliefs
        beliefs_invalidated = 0
        if affected_belief_ids:
            placeholders = ",".join("?" * len(affected_belief_ids))
            conn.execute(
                f"""UPDATE beliefs SET status = 'under_review'
                    WHERE id IN ({placeholders})""",
                list(affected_belief_ids),
            )
            beliefs_invalidated = len(affected_belief_ids)

        conn.commit()

        # Re-run relational resolver after bulk reassignment.
        # If the anchor person changed (e.g., Stephen Andrews -> Stephen Weber),
        # relational references like "Stephen's son" may now resolve differently.
        resolver_stats = None
        try:
            from sauron.extraction.entity_resolver import resolve_claim_entities
            resolver_stats = resolve_claim_entities(conversation_id)
            if resolver_stats and resolver_stats.get("resolved", 0) > 0:
                logger.info(
                    f"Post-reassign resolver: {resolver_stats['resolved']} claims auto-resolved"
                )
        except Exception as e:
            logger.warning(f"Post-reassign resolver failed (non-fatal): {e}")

        logger.info(
            f"Bulk reassign {conversation_id[:8]}: {from_name} → {to_name} | "
            f"{claims_updated} claims, {transcripts_updated} transcripts, "
            f"{beliefs_invalidated} beliefs invalidated, "
            f"{len(ambiguous_claim_ids)} ambiguous flagged"
        )

        return {
            "dry_run": False,
            "from_entity": from_name,
            "to_entity": to_name,
            "claims_updated": claims_updated,
            "transcripts_updated": transcripts_updated,
            "beliefs_invalidated": beliefs_invalidated,
            "ambiguous_claims_flagged": len(ambiguous_claim_ids),
            "transcript_review_recommended": transcripts_updated > 0,
            "resolver_stats": resolver_stats,
        }

    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.exception("Bulk reassignment failed")
        raise HTTPException(500, "Bulk reassignment failed")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
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



# ═══════════════════════════════════════════════════════════════
# Phase 3: People & Routing Preview Endpoints
# ═══════════════════════════════════════════════════════════════

SELF_ENTITY_ID = "948c2cf3-9a8c-49d5-853c-d54e91b7133a"

# Singular→plural mapping for synthesis object types
_OBJ_TYPE_PLURAL = {
    "standing_offer": "standing_offers",
    "scheduling_lead": "scheduling_leads",
    "graph_edge": "graph_edges",
    "new_contact": "new_contacts_mentioned",
}
_OBJ_TYPE_SINGULAR = {v: k for k, v in _OBJ_TYPE_PLURAL.items()}


class ConfirmPersonRequest(BaseModel):
    original_name: str
    entity_id: str


class LinkRemainingRequest(BaseModel):
    entity_id: str
    subject_name: str


class SkipPersonRequest(BaseModel):
    original_name: str
    entity_id: Optional[str] = None


@router.get("/{conversation_id}/people")
def list_conversation_people(conversation_id: str):
    """List all people referenced in a conversation with resolution status.

    Returns each unique person with:
    - status: confirmed (green), auto_resolved (yellow), provisional (red), unresolved (red)
    - is_self: True if this is Stephen Andrews
    - claim_count, roles, link_sources
    """
    conn = get_connection()
    try:
        people_map = {}  # key: entity_id or "unresolved:<lowername>"

        # ── Source 1: Subject references from event_claims ──
        subjects = conn.execute("""
            SELECT ec.subject_name, ec.subject_entity_id,
                   uc.canonical_name, uc.is_confirmed
            FROM event_claims ec
            LEFT JOIN unified_contacts uc ON uc.id = ec.subject_entity_id
            WHERE ec.conversation_id = ?
              AND ec.subject_name IS NOT NULL
              AND (ec.review_status IS NULL OR ec.review_status != 'dismissed')
        """, (conversation_id,)).fetchall()

        for s in subjects:
            entity_id = s["subject_entity_id"]
            name = s["subject_name"]
            key = entity_id if entity_id else f"unresolved:{name.strip().lower()}"

            if key not in people_map:
                people_map[key] = {
                    "original_names": set(),
                    "entity_id": entity_id,
                    "canonical_name": s["canonical_name"],
                    "is_confirmed": s["is_confirmed"],
                    "subject_claim_count": 0,
                    "roles": set(),
                    "link_sources": set(),
                }
            people_map[key]["original_names"].add(name)
            people_map[key]["subject_claim_count"] += 1
            people_map[key]["roles"].add("subject")

        # ── Source 2: claim_entities (subject + target roles) ──
        ce_rows = conn.execute("""
            SELECT ce.entity_name, ce.entity_id, ce.role, ce.link_source,
                   uc.canonical_name, uc.is_confirmed
            FROM claim_entities ce
            JOIN event_claims ec ON ec.id = ce.claim_id
            LEFT JOIN unified_contacts uc ON uc.id = ce.entity_id
            WHERE ec.conversation_id = ?
              AND (ec.review_status IS NULL OR ec.review_status != 'dismissed')
        """, (conversation_id,)).fetchall()

        for ce in ce_rows:
            entity_id = ce["entity_id"]
            name = ce["entity_name"]
            key = entity_id if entity_id else f"unresolved:{name.strip().lower()}"

            if key not in people_map:
                people_map[key] = {
                    "original_names": set(),
                    "entity_id": entity_id,
                    "canonical_name": ce["canonical_name"],
                    "is_confirmed": ce["is_confirmed"],
                    "subject_claim_count": 0,
                    "roles": set(),
                    "link_sources": set(),
                }
            people_map[key]["original_names"].add(name)
            people_map[key]["roles"].add(ce["role"])
            if ce["link_source"]:
                people_map[key]["link_sources"].add(ce["link_source"])
            # Update canonical/confirmed if we got better data
            if entity_id and ce["canonical_name"] and not people_map[key]["canonical_name"]:
                people_map[key]["canonical_name"] = ce["canonical_name"]
                people_map[key]["is_confirmed"] = ce["is_confirmed"]

        # ── Source 3: synthesis_entity_links ──
        sel_rows = conn.execute("""
            SELECT sel.original_name, sel.resolved_entity_id, sel.link_source,
                   sel.confidence, uc.canonical_name, uc.is_confirmed
            FROM synthesis_entity_links sel
            LEFT JOIN unified_contacts uc ON uc.id = sel.resolved_entity_id
            WHERE sel.conversation_id = ?
        """, (conversation_id,)).fetchall()

        for sel in sel_rows:
            entity_id = sel["resolved_entity_id"]
            name = sel["original_name"]
            key = entity_id if entity_id else f"unresolved:{name.strip().lower()}"

            if key not in people_map:
                people_map[key] = {
                    "original_names": set(),
                    "entity_id": entity_id,
                    "canonical_name": sel["canonical_name"],
                    "is_confirmed": sel["is_confirmed"],
                    "subject_claim_count": 0,
                    "roles": set(),
                    "link_sources": set(),
                }
            people_map[key]["original_names"].add(name)
            if sel["link_source"]:
                people_map[key]["link_sources"].add(sel["link_source"])

        # ── Consolidate: merge unresolved into matching resolved person ──
        # If "unresolved:daniel park" exists AND a resolved entity has
        # canonical_name "Daniel Park" (case-insensitive), merge claims into
        # the resolved entry. Display-only — no DB mutation.
        resolved_by_name = {}  # lowered canonical_name -> key
        for key, data in people_map.items():
            if data["entity_id"] and data["canonical_name"]:
                resolved_by_name[data["canonical_name"].strip().lower()] = key

        unresolved_keys = [k for k in people_map if k.startswith("unresolved:")]
        for ukey in unresolved_keys:
            udata = people_map[ukey]
            # Check each original_name against resolved canonical names
            for uname in list(udata["original_names"]):
                match_key = resolved_by_name.get(uname.strip().lower())
                if match_key and match_key in people_map:
                    # Merge into resolved entry
                    rdata = people_map[match_key]
                    rdata["original_names"] |= udata["original_names"]
                    rdata["subject_claim_count"] += udata["subject_claim_count"]
                    rdata["unlinked_claim_count"] = rdata.get("unlinked_claim_count", 0) + udata["subject_claim_count"]
                    rdata["roles"] |= udata["roles"]
                    rdata["link_sources"] |= udata["link_sources"]
                    del people_map[ukey]
                    break  # This unresolved key is consumed

        # ── Build response ──
        people = []
        for key, data in people_map.items():
            entity_id = data["entity_id"]
            link_sources = data["link_sources"]
            is_confirmed = data["is_confirmed"]

            # Determine status
            if "skipped" in link_sources:
                status = "skipped"
            elif "dismissed" in link_sources:
                status = "dismissed"
            elif entity_id is None:
                status = "unresolved"
            elif is_confirmed == 0:
                status = "provisional"
            elif link_sources & {"user", "speaker_cascade", "confirm_person", "bulk_reassign"}:
                status = "confirmed"
            else:
                status = "auto_resolved"

            people.append({
                "original_name": sorted(data["original_names"])[0],
                "all_names": sorted(data["original_names"]),
                "entity_id": entity_id,
                "canonical_name": data["canonical_name"],
                "status": status,
                "is_self": entity_id == SELF_ENTITY_ID,
                "is_provisional": is_confirmed == 0 if entity_id else False,
                "claim_count": data["subject_claim_count"],
                "unlinked_claim_count": data.get("unlinked_claim_count", 0),
                "roles": sorted(data["roles"]),
                "link_sources": sorted(data["link_sources"]),
            })

        # Sort: unresolved first, then provisional, auto_resolved, confirmed
        status_order = {"unresolved": 0, "provisional": 1, "auto_resolved": 2, "confirmed": 3, "skipped": 4}
        people.sort(key=lambda p: (status_order.get(p["status"], 99), p["original_name"]))

        return {"people": people, "total": len(people)}
    finally:
        conn.close()


@router.post("/{conversation_id}/confirm-person")
def confirm_person(conversation_id: str, request: ConfirmPersonRequest):
    """Confirm an auto-resolved person mapping (yellow -> green).

    Only for already-resolved people. Provisional contacts use
    graph.py endpoints (link_provisional_to_existing, confirm_provisional_contact).
    """
    conn = get_connection()
    try:
        # Verify entity is a confirmed contact (not provisional)
        contact = conn.execute(
            "SELECT id, canonical_name, is_confirmed FROM unified_contacts WHERE id = ?",
            (request.entity_id,),
        ).fetchone()

        if not contact:
            raise HTTPException(404, "Contact not found")
        if not contact["is_confirmed"]:
            raise HTTPException(
                400,
                "Contact is provisional. Use /api/graph/provisional/{id}/link "
                "or /api/graph/provisional/{id}/confirm instead.",
            )

        canonical_name = contact["canonical_name"]

        # Collect all original names for this entity in this conversation
        original_names = {request.original_name}

        # From event_claims
        claims = conn.execute("""
            SELECT DISTINCT subject_name FROM event_claims
            WHERE conversation_id = ? AND subject_entity_id = ?
              AND subject_name IS NOT NULL
        """, (conversation_id, request.entity_id)).fetchall()
        for c in claims:
            original_names.add(c["subject_name"])

        # From synthesis_entity_links
        sel_names = conn.execute("""
            SELECT DISTINCT original_name FROM synthesis_entity_links
            WHERE conversation_id = ? AND resolved_entity_id = ?
        """, (conversation_id, request.entity_id)).fetchall()
        for s in sel_names:
            original_names.add(s["original_name"])

        # Run cascade
        from sauron.extraction.cascade import cascade_entity_confirmation
        cascade_stats = cascade_entity_confirmation(
            conn, request.entity_id, canonical_name,
            list(original_names), conversation_id,
            source="confirm_person",
        )

        # Upgrade link_source from auto -> user for claim_entities in this conversation
        conn.execute("""
            UPDATE claim_entities SET link_source = 'user'
            WHERE entity_id = ?
              AND link_source IN ('auto_synthesis', 'resolver', 'model')
              AND claim_id IN (
                  SELECT id FROM event_claims WHERE conversation_id = ?
              )
        """, (request.entity_id, conversation_id))

        # Also upgrade synthesis_entity_links (including overriding 'skipped')
        conn.execute("""
            UPDATE synthesis_entity_links SET link_source = 'user'
            WHERE resolved_entity_id = ?
              AND conversation_id = ?
              AND link_source != 'user'
        """, (request.entity_id, conversation_id))

        conn.commit()
        return {
            "status": "ok",
            "confirmed": canonical_name,
            "entity_id": request.entity_id,
            "cascade": cascade_stats,
        }
    finally:
        conn.close()


@router.post("/{conversation_id}/link-remaining-claims")
def link_remaining_claims(conversation_id: str, request: LinkRemainingRequest):
    """Link orphaned claims to a confirmed entity by exact name match.

    For claims where subject_name matches but subject_entity_id is NULL.
    Does not overwrite existing links. Does not touch dismissed claims.
    Requires the entity to be a confirmed contact.
    """
    conn = get_connection()
    try:
        # Verify entity is confirmed
        contact = conn.execute(
            "SELECT id, canonical_name, is_confirmed FROM unified_contacts WHERE id = ?",
            (request.entity_id,),
        ).fetchone()
        if not contact:
            raise HTTPException(404, "Contact not found")
        if not contact["is_confirmed"]:
            raise HTTPException(400, "Contact is not confirmed")

        canonical_name = contact["canonical_name"]

        # Find orphaned claims: same conversation, exact name match, NULL entity, not dismissed
        orphans = conn.execute(
            """SELECT id, subject_name FROM event_claims
               WHERE conversation_id = ?
                 AND LOWER(TRIM(subject_name)) = LOWER(TRIM(?))
                 AND subject_entity_id IS NULL
                 AND (review_status IS NULL OR review_status != 'dismissed')""",
            (conversation_id, request.subject_name),
        ).fetchall()

        if not orphans:
            return {"linked": 0, "entity_id": request.entity_id}

        from sauron.api.corrections import sync_claim_entities_subject

        linked = 0
        for orphan in orphans:
            try:
                sync_claim_entities_subject(
                    conn, orphan["id"], request.entity_id,
                    canonical_name, "user_link_remaining",
                )
                linked += 1
            except Exception:
                logger.exception(f"link-remaining failed for claim {orphan['id'][:8]}")

        conn.commit()
        return {"linked": linked, "entity_id": request.entity_id, "canonical_name": canonical_name}
    finally:
        conn.close()


@router.post("/{conversation_id}/skip-person")
def skip_person(conversation_id: str, request: SkipPersonRequest):
    """Mark a person as skipped - don't prompt for review again."""
    conn = get_connection()
    try:
        updated = 0

        # Update synthesis_entity_links by name
        updated += conn.execute("""
            UPDATE synthesis_entity_links SET link_source = 'skipped'
            WHERE conversation_id = ?
              AND LOWER(TRIM(original_name)) = LOWER(?)
              AND link_source != 'skipped'
        """, (conversation_id, request.original_name.strip())).rowcount

        # If entity_id provided, also skip by entity_id
        if request.entity_id:
            updated += conn.execute("""
                UPDATE synthesis_entity_links SET link_source = 'skipped'
                WHERE conversation_id = ?
                  AND resolved_entity_id = ?
                  AND link_source != 'skipped'
            """, (conversation_id, request.entity_id)).rowcount

        # If no rows were updated, this person has no synthesis_entity_links rows
        # (e.g. unresolved people only referenced in claims). Insert a skipped row.
        if updated == 0:
            import uuid as _uuid
            conn.execute("""
                INSERT INTO synthesis_entity_links
                    (id, conversation_id, object_type, object_index, field_name,
                     original_name, resolved_entity_id, link_source, confidence)
                VALUES (?, ?, '_skip', 0, '_skip', ?, ?, 'skipped', 0.0)
            """, (str(_uuid.uuid4()), conversation_id, request.original_name.strip(),
                  request.entity_id))
            updated = 1

        conn.commit()
        return {
            "status": "ok",
            "skipped_name": request.original_name,
            "links_updated": updated,
        }
    finally:
        conn.close()


@router.post("/{conversation_id}/unskip-person")
def unskip_person(conversation_id: str, request: SkipPersonRequest):
    """Revert a skipped person back to their pre-skip state."""
    conn = get_connection()
    try:
        updated = 0

        # Revert synthesis_entity_links by name
        updated += conn.execute("""
            UPDATE synthesis_entity_links SET link_source = 'auto_synthesis'
            WHERE conversation_id = ?
              AND LOWER(TRIM(original_name)) = LOWER(?)
              AND link_source IN ('skipped', 'dismissed')
        """, (conversation_id, request.original_name.strip())).rowcount

        # If entity_id provided, also revert by entity_id
        if request.entity_id:
            updated += conn.execute("""
                UPDATE synthesis_entity_links SET link_source = 'auto_synthesis'
                WHERE conversation_id = ?
                  AND resolved_entity_id = ?
                  AND link_source IN ('skipped', 'dismissed')
            """, (conversation_id, request.entity_id)).rowcount

        conn.commit()
        return {
            "status": "ok",
            "unskipped_name": request.original_name,
            "links_updated": updated,
        }
    finally:
        conn.close()


@router.post("/{conversation_id}/dismiss-person")
def dismiss_person(conversation_id: str, request: SkipPersonRequest):
    """Dismiss a person from this conversation's review.

    Works for both resolved and unresolved people. Inserts/updates
    synthesis_entity_links with link_source='dismissed'.
    """
    import uuid as _uuid
    conn = get_connection()
    try:
        updated = 0

        # Try UPDATE existing rows first
        updated += conn.execute("""
            UPDATE synthesis_entity_links SET link_source = 'dismissed'
            WHERE conversation_id = ?
              AND LOWER(TRIM(original_name)) = LOWER(?)
              AND link_source != 'dismissed'
        """, (conversation_id, request.original_name.strip())).rowcount

        if request.entity_id:
            updated += conn.execute("""
                UPDATE synthesis_entity_links SET link_source = 'dismissed'
                WHERE conversation_id = ?
                  AND resolved_entity_id = ?
                  AND link_source != 'dismissed'
            """, (conversation_id, request.entity_id)).rowcount

        # If no rows existed, insert a dismissed sentinel row
        if updated == 0:
            conn.execute("""
                INSERT INTO synthesis_entity_links
                    (id, conversation_id, object_type, object_index, field_name,
                     original_name, resolved_entity_id, link_source, confidence)
                VALUES (?, ?, '_skip', 0, '_skip', ?, ?, 'dismissed', 0.0)
            """, (str(_uuid.uuid4()), conversation_id, request.original_name.strip(),
                  request.entity_id))
            updated = 1

        conn.commit()
        return {
            "status": "ok",
            "dismissed_name": request.original_name,
            "links_updated": updated,
        }
    finally:
        conn.close()


def _get_object_summary(obj_type_plural: str, item: dict) -> str:
    """Extract a human-readable summary from a synthesis object."""
    if obj_type_plural == "standing_offers":
        return (item.get("description") or item.get("offer") or "")[:120]
    elif obj_type_plural == "scheduling_leads":
        return (item.get("description") or item.get("suggested_meeting") or "")[:120]
    elif obj_type_plural == "graph_edges":
        f = item.get("from_entity", "")
        t = item.get("to_entity", "")
        r = item.get("edge_type") or item.get("relationship", "")
        return f"{f} -> {r} -> {t}"
    elif obj_type_plural == "new_contacts_mentioned":
        return (item.get("name") or "") + ": " + (item.get("context") or "")[:80]
    elif obj_type_plural == "contact_commitments":
        return (item.get("description") or "")[:120]
    elif obj_type_plural == "my_commitments":
        return (item.get("description") or "")[:120]
    elif obj_type_plural == "follow_ups":
        return (item.get("description") or "")[:120]
    elif obj_type_plural == "policy_positions":
        topic = item.get('topic', '')
        return f"{item.get('person', '')}: {item.get('position', '')} {topic}"[:120]
    return str(item)[:120]


@router.get("/{conversation_id}/routing-preview")
def get_routing_preview(conversation_id: str):
    """Preview routing readiness for synthesis objects in a conversation.

    Groups by synthesis object type (standing_offers, scheduling_leads,
    graph_edges, etc). Each object shows entity resolution status and
    which person is blocking it.
    """
    conn = get_connection()
    try:
        # Get the pass-3 synthesis extraction
        extraction = conn.execute("""
            SELECT extraction_json FROM extractions
            WHERE conversation_id = ? AND pass_number = 3
            ORDER BY rowid DESC LIMIT 1
        """, (conversation_id,)).fetchone()

        if not extraction:
            return {"ready_count": 0, "blocked_count": 0, "objects": {}}

        synthesis = json.loads(extraction["extraction_json"])

        # Get all synthesis_entity_links for this conversation
        links = conn.execute("""
            SELECT sel.object_type, sel.object_index, sel.field_name,
                   sel.original_name, sel.resolved_entity_id, sel.link_source,
                   sel.confidence,
                   uc.canonical_name, uc.is_confirmed
            FROM synthesis_entity_links sel
            LEFT JOIN unified_contacts uc ON uc.id = sel.resolved_entity_id
            WHERE sel.conversation_id = ?
        """, (conversation_id,)).fetchall()

        # Group links by (object_type, object_index)
        link_map = {}
        for link in links:
            key = (link["object_type"], link["object_index"])
            if key not in link_map:
                link_map[key] = []
            link_map[key].append(dict(link))

        # Object types to include in routing preview (person-bearing objects)
        ROUTABLE_TYPES = [
            "standing_offers", "scheduling_leads", "graph_edges",
            "contact_commitments", "policy_positions",
        ]

        objects = {}
        ready_count = 0
        blocked_count = 0
        skipped_count = 0

        for obj_type_plural in ROUTABLE_TYPES:
            items = synthesis.get(obj_type_plural, [])
            if not items:
                continue

            obj_type_singular = _OBJ_TYPE_SINGULAR.get(obj_type_plural, obj_type_plural.rstrip("s"))
            obj_list = []

            for idx, item in enumerate(items):
                people_refs = link_map.get((obj_type_singular, idx), [])

                blockers = []
                people = []
                for ref in people_refs:
                    if ref["link_source"] == "skipped":
                        people.append({
                            "name": ref["original_name"],
                            "entity_id": ref["resolved_entity_id"],
                            "canonical_name": ref["canonical_name"],
                            "resolved": True,
                            "skipped": True,
                        })
                    elif ref["resolved_entity_id"] and ref["is_confirmed"]:
                        people.append({
                            "name": ref["original_name"],
                            "entity_id": ref["resolved_entity_id"],
                            "canonical_name": ref["canonical_name"],
                            "resolved": True,
                            "skipped": False,
                        })
                    else:
                        reason = "unresolved" if not ref["resolved_entity_id"] else "provisional"
                        blockers.append(f"{ref['original_name']} is {reason}")
                        people.append({
                            "name": ref["original_name"],
                            "entity_id": ref["resolved_entity_id"],
                            "canonical_name": ref.get("canonical_name"),
                            "resolved": False,
                            "skipped": False,
                        })

                has_skipped = any(p.get("skipped") for p in people)
                if blockers:
                    status = "blocked"
                    blocked_count += 1
                elif has_skipped:
                    status = "skipped"
                    skipped_count += 1
                else:
                    status = "ready"
                    ready_count += 1

                summary = _get_object_summary(obj_type_plural, item)

                entry = {
                    "index": idx,
                    "summary": summary,
                    "status": status,
                    "people": people,
                }
                if blockers:
                    entry["blocker"] = "; ".join(blockers)

                obj_list.append(entry)

            if obj_list:
                objects[obj_type_plural] = obj_list

        return {
            "ready_count": ready_count,
            "blocked_count": blocked_count,
            "skipped_count": skipped_count,
            "objects": objects,
        }
    finally:
        conn.close()
