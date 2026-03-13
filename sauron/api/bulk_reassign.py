"""Bulk reassignment endpoint (extracted from conversations.py)."""

import json
import logging
import re
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sauron.db.connection import get_connection
from sauron.api.entity_helpers import _has_ambiguous_name_ref, replace_confirmed_name, replace_name_in_text

logger = logging.getLogger(__name__)
router = APIRouter()


class BulkReassignRequest(BaseModel):
    from_entity_id: str
    to_entity_id: str
    scope: str = "all"  # "all" | "claims_only" | "transcript_only"
    dry_run: bool = True


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
            f"Bulk reassign {conversation_id[:8]}: {from_name} \u2192 {to_name} | "
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
