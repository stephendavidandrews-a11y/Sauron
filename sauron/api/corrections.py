"""Correction API — object-level fixes with error taxonomy per Iterative_Improvement_Spec.

V8: Added claim_entities sync on entity-link, review_status tracking,
    user correction protection.
"""

import json
import logging

import numpy as np
import re as _re
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from sauron.db.connection import get_connection
from sauron.api.relational_terms import RELATIONAL_TERMS, PLURAL_TERMS, ALL_TERMS, is_relational_term
from sauron.api.entity_helpers import replace_confirmed_name, replace_name_in_text

router = APIRouter(prefix="/correct", tags=["corrections"])

# ---------------------------------------------------------------------------
# Feature 6: Dynamic analysis trigger
# ---------------------------------------------------------------------------

def _check_dynamic_trigger(conn):
    """Check if unprocessed corrections exceed threshold and trigger analysis."""
    try:
        latest_amendment_date = conn.execute(
            "SELECT MAX(created_at) FROM prompt_amendments"
        ).fetchone()[0] or "1970-01-01T00:00:00"
        pending = conn.execute(
            "SELECT COUNT(*) FROM correction_events WHERE created_at > ?",
            (latest_amendment_date,)
        ).fetchone()[0]

        DYNAMIC_TRIGGER_THRESHOLD = 25

        if pending >= DYNAMIC_TRIGGER_THRESHOLD:
            import threading
            def _run_analysis():
                try:
                    from sauron.learning.amendments import analyze_corrections_and_amend
                    result = analyze_corrections_and_amend()
                    if result:
                        logger.info("Dynamic trigger: generated new amendment from %d corrections", pending)
                except Exception:
                    logger.exception("Dynamic trigger analysis failed")
            threading.Thread(target=_run_analysis, daemon=True).start()
    except Exception:
        logger.exception("Dynamic trigger check failed (non-fatal)")




logger = logging.getLogger(__name__)

# --- Relational reference detection ---
# Plural-to-singular mapping for relationship normalization
RELATIONAL_PATTERNS = [
    _re.compile(r"\b(?:my|his|her|their|\w+'s)\s+(\w+)\b", _re.IGNORECASE),
    _re.compile(r"\b(\w+'s)\s+(\w+)\b", _re.IGNORECASE),
]


def _detect_relational_reference(claim_text: str, anchor_names: list[str]) -> dict | None:
    """Detect if claim_text contains a relational reference to an anchor person.

    Returns {"anchor_name": ..., "relationship": ..., "phrase": ...} or None.
    Example: "Stephen Weber's son" -> {"anchor_name": "Stephen Weber", "relationship": "son", "phrase": "Stephen Weber's son"}
    """
    if not claim_text or not anchor_names:
        return None

    text_lower = claim_text.lower()

    for anchor in anchor_names:
        if not anchor:
            continue
        anchor_lower = anchor.lower()
        first_name = anchor.split()[0].lower() if anchor else ""

        # Check for "Name's [relation]" patterns
        for possessive in [f"{anchor_lower}'s", f"{first_name}'s"]:
            idx = text_lower.find(possessive)
            if idx == -1:
                continue
            after = text_lower[idx + len(possessive):].strip()
            for term in RELATIONAL_TERMS:
                if after.startswith(term):
                    # Verify it's a word boundary
                    end_pos = len(term)
                    if end_pos >= len(after) or not after[end_pos].isalpha():
                        phrase_start = idx
                        phrase_end = idx + len(possessive) + 1 + end_pos
                        phrase = claim_text[phrase_start:phrase_end].strip()
                        is_plural = term in PLURAL_TERMS
                        return {
                            "anchor_name": anchor,
                            "relationship": term,
                            "is_plural": is_plural,
                            "phrase": phrase,
                        }

        # Check for "my [relation]" pattern (anchor = speaker)
        for pattern in [r"\b(my|his|her|their)\s+(\w+)\b"]:
            for m in _re.finditer(pattern, claim_text, _re.IGNORECASE):
                term = m.group(2).lower()
                if term in RELATIONAL_TERMS:
                    is_plural = term in PLURAL_TERMS
                    return {
                        "anchor_name": anchor,
                        "relationship": term,
                        "is_plural": is_plural,
                        "phrase": m.group(0),
                    }

    return None


# --- Error taxonomy ---
ERROR_TYPES = [
    "speaker_resolution",
    "bad_episode_segmentation",
    "missed_claim",
    "hallucinated_claim",
    "wrong_claim_type",
    "wrong_modality",
    "wrong_polarity",
    "wrong_confidence",
    "wrong_stability",
    "bad_entity_linking",
    "bad_commitment_extraction",
    "bad_belief_synthesis",
    "overstated_position",
    "bad_recommendation",
    "claim_text_edited",
    "provisional_contact_merged",
    "wrong_commitment_firmness",
    "wrong_commitment_direction",
    "wrong_commitment_deadline",
    "wrong_commitment_condition",
    "wrong_commitment_time_horizon",
    "wrong_commitment_action",
]

# Generalization gating thresholds
FAST_GENERALIZE = {
    "wrong_modality", "wrong_claim_type", "wrong_confidence",
    "bad_commitment_extraction", "overstated_position", "wrong_commitment_firmness",
    "wrong_commitment_direction", "wrong_commitment_deadline",
    "wrong_commitment_condition", "wrong_commitment_time_horizon", "wrong_commitment_action",
}  # 3 corrections to generalize
SLOW_GENERALIZE = ERROR_TYPES  # everything else: 5 corrections


class CorrectionEvent(BaseModel):
    conversation_id: str
    error_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    episode_id: Optional[str] = None
    claim_id: Optional[str] = None
    belief_id: Optional[str] = None
    user_feedback: Optional[str] = None
    correction_source: str = "manual_ui"

    @field_validator("error_type")
    @classmethod
    def validate_error_type(cls, v):
        if v not in ERROR_TYPES:
            raise ValueError(f"Invalid error_type: {v}. Must be one of: {ERROR_TYPES}")
        return v


class ClaimCorrection(BaseModel):
    """Convenience model for common claim corrections."""
    conversation_id: str
    claim_id: str
    error_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    user_feedback: Optional[str] = None

    @field_validator("error_type")
    @classmethod
    def validate_error_type(cls, v):
        if v not in ERROR_TYPES:
            raise ValueError(f"Invalid error_type: {v}. Must be one of: {ERROR_TYPES}")
        return v



class BatchClaimCorrection(BaseModel):
    """Batch correction for multiple fields on a single claim."""
    conversation_id: str
    claim_id: str
    corrections: dict  # field_name -> new_value
    user_feedback: Optional[str] = None



class AddClaimRequest(BaseModel):
    """Create a new user-authored claim."""
    conversation_id: str
    episode_id: Optional[str] = None
    claim_type: str
    claim_text: str
    subject_name: Optional[str] = None
    subject_entity_id: Optional[str] = None
    direction: Optional[str] = None
    firmness: Optional[str] = None
    has_specific_action: Optional[bool] = None
    has_deadline: Optional[bool] = None
    time_horizon: Optional[str] = None
    has_condition: Optional[bool] = None
    condition_text: Optional[str] = None
    evidence_quote: Optional[str] = None


class ReassignClaimRequest(BaseModel):
    """Reassign a claim to a different episode."""
    claim_id: str
    conversation_id: str
    episode_id: Optional[str] = None  # None = orphan



class SpeakerCorrection(BaseModel):
    conversation_id: str
    speaker_label: str
    correct_contact_id: str


class BeliefCorrection(BaseModel):
    belief_id: str
    new_status: str
    user_feedback: Optional[str] = None


class EntityLink(BaseModel):
    """Link a claim's subject to a unified_contacts record."""
    conversation_id: str
    claim_id: str
    contact_id: str
    old_subject_name: Optional[str] = None
    user_feedback: Optional[str] = None


def sync_claim_entities_subject(conn, claim_id: str, entity_id: str, entity_name: str, link_source: str = "user"):
    """Sync the claim_entities junction table for a subject role.

    Source of truth sync rule: whenever claim_entities changes for a claim,
    update subject_entity_id on event_claims to match the primary role='subject'
    entity. There must never be drift between the two.
    """
    # Check if this entity is already linked to this claim
    existing = conn.execute(
        "SELECT id FROM claim_entities WHERE claim_id = ? AND entity_id = ?",
        (claim_id, entity_id),
    ).fetchone()

    if existing:
        # Already linked — just update the name/source
        conn.execute(
            "UPDATE claim_entities SET entity_name = ?, link_source = ? WHERE id = ?",
            (entity_name, link_source, existing["id"]),
        )
    else:
        # Check if there's already a subject AND it's model-linked (auto).
        # If so, replace it. If user-linked, ADD alongside it.
        model_subject = conn.execute(
            "SELECT id FROM claim_entities WHERE claim_id = ? AND role = 'subject' AND link_source = 'model'",
            (claim_id,),
        ).fetchone()
        if model_subject:
            # Replace auto-linked subject with user-linked one
            conn.execute("DELETE FROM claim_entities WHERE id = ?", (model_subject["id"],))

        # Insert new entry
        conn.execute(
            """INSERT INTO claim_entities
               (id, claim_id, entity_id, entity_name, role, confidence, link_source)
               VALUES (?, ?, ?, ?, 'subject', NULL, ?)""",
            (str(uuid.uuid4()), claim_id, entity_id, entity_name, link_source),
        )

    # Sync event_claims.subject_entity_id to the FIRST user-linked entity, or most recent
    first_subject = conn.execute(
        """SELECT entity_id, entity_name FROM claim_entities
           WHERE claim_id = ? AND role = 'subject'
           ORDER BY link_source = 'user' DESC, created_at ASC LIMIT 1""",
        (claim_id,),
    ).fetchone()
    if first_subject:
        conn.execute(
            "UPDATE event_claims SET subject_entity_id = ?, subject_name = ? WHERE id = ?",
            (first_subject["entity_id"], first_subject["entity_name"], claim_id),
        )


@router.get("/error-types")
def list_error_types():
    """List all valid error types in the taxonomy."""
    return {
        "error_types": ERROR_TYPES,
        "fast_generalize": list(FAST_GENERALIZE),
        "fast_threshold": 3,
        "slow_threshold": 5,
    }


@router.post("/event")
def log_correction_event(event: CorrectionEvent):
    """Log a correction event and apply the object-level fix."""
    conn = get_connection()
    try:
        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, episode_id, claim_id, belief_id,
                error_type, old_value, new_value, user_feedback, correction_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, event.conversation_id, event.episode_id, event.claim_id,
             event.belief_id, event.error_type, event.old_value, event.new_value,
             event.user_feedback, event.correction_source),
        )

        # If a claim was corrected and it supports beliefs, mark those beliefs under_review
        if event.claim_id:
            _affected = conn.execute(
                """SELECT DISTINCT b.id, b.status FROM beliefs b
                   JOIN belief_evidence be ON be.belief_id = b.id
                   WHERE be.claim_id = ? AND b.status != 'under_review'""",
                (event.claim_id,),
            ).fetchall()
            conn.execute(
                """UPDATE beliefs SET status = 'under_review'
                   WHERE id IN (
                       SELECT DISTINCT be.belief_id FROM belief_evidence be
                       WHERE be.claim_id = ?
                   )""",
                (event.claim_id,),
            )
            for _ab in _affected:
                conn.execute(
                    """INSERT INTO belief_transitions
                       (id, belief_id, old_status, new_status, driver, source_correction_id)
                       VALUES (?, ?, ?, 'under_review', 'correction', ?)""",
                    (str(uuid.uuid4()), _ab["id"], _ab["status"], event_id),
                )

            # Queue re-synthesis for affected beliefs (Feature 1)
            for _ab in _affected:
                try:
                    from sauron.learning.resynthesize import queue_resynthesis
                    queue_resynthesis(_ab["id"], event_id)
                except Exception:
                    logger.exception("Failed to queue belief re-synthesis")

        conn.commit()

        # Check dynamic analysis trigger (Feature 6)
        _check_dynamic_trigger(conn)

        return {"status": "ok", "event_id": event_id, "error_type": event.error_type}
    finally:
        conn.close()


@router.post("/claim")
def correct_claim(correction: ClaimCorrection):
    """Correct a specific claim — edit text, change type, dismiss, etc.

    Sets review_status to 'user_corrected' to protect from pipeline overwrite.
    """
    conn = get_connection()
    try:
        event_id = str(uuid.uuid4())

        # Apply object-level fix based on error_type
        if correction.error_type == "wrong_claim_type" and correction.new_value:
            conn.execute(
                "UPDATE event_claims SET claim_type = ? WHERE id = ?",
                (correction.new_value, correction.claim_id),
            )
        elif correction.error_type in ("wrong_modality", "wrong_polarity", "wrong_stability"):
            field_map = {
                "wrong_modality": "modality",
                "wrong_polarity": "polarity",
                "wrong_stability": "stability",
            }
            field = field_map[correction.error_type]
            if correction.new_value:
                conn.execute(
                    f"UPDATE event_claims SET {field} = ? WHERE id = ?",
                    (correction.new_value, correction.claim_id),
                )
        elif correction.error_type == "wrong_confidence" and correction.new_value:
            try:
                conf = float(correction.new_value)
                conn.execute(
                    "UPDATE event_claims SET confidence = ? WHERE id = ?",
                    (conf, correction.claim_id),
                )
            except ValueError:
                pass
        elif correction.new_value:
            conn.execute(
                "UPDATE event_claims SET claim_text = ? WHERE id = ?",
                (correction.new_value, correction.claim_id),
            )
            # Mark text as user-edited so entity linking won't overwrite it
            conn.execute(
                "UPDATE event_claims SET text_user_edited = 1 WHERE id = ?",
                (correction.claim_id,),
            )

        # Mark as user_corrected — pipeline reruns will skip this claim
        conn.execute(
            "UPDATE event_claims SET review_status = 'user_corrected' WHERE id = ?",
            (correction.claim_id,),
        )

        # Log correction event
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, claim_id, error_type, old_value, new_value, user_feedback, correction_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'manual_ui')""",
            (event_id, correction.conversation_id, correction.claim_id,
             correction.error_type, correction.old_value, correction.new_value,
             correction.user_feedback),
        )

        # Mark supporting beliefs as under_review
        _affected = conn.execute(
            """SELECT DISTINCT b.id, b.status FROM beliefs b
               JOIN belief_evidence be ON be.belief_id = b.id
               WHERE be.claim_id = ? AND b.status != 'under_review'""",
            (correction.claim_id,),
        ).fetchall()
        conn.execute(
            """UPDATE beliefs SET status = 'under_review'
               WHERE id IN (
                   SELECT DISTINCT be.belief_id FROM belief_evidence be
                   WHERE be.claim_id = ?
               )""",
            (correction.claim_id,),
        )
        for _ab in _affected:
            conn.execute(
                """INSERT INTO belief_transitions
                   (id, belief_id, old_status, new_status, driver, source_correction_id)
                   VALUES (?, ?, ?, 'under_review', 'correction', ?)""",
                (str(uuid.uuid4()), _ab["id"], _ab["status"], event_id),
            )

        # Queue re-synthesis for affected beliefs (Feature 1)
        for _ab in _affected:
            try:
                from sauron.learning.resynthesize import queue_resynthesis
                queue_resynthesis(_ab["id"], event_id)
            except Exception:
                logger.exception("Failed to queue belief re-synthesis")

        conn.commit()

        # Check dynamic analysis trigger (Feature 6)
        _check_dynamic_trigger(conn)

        return {"status": "ok", "event_id": event_id}
    finally:
        conn.close()


@router.post("/entity-link")
def link_entity(link: EntityLink):
    """Link a claim's subject to a unified_contacts record.

    This is DIFFERENT from speaker correction:
    - Speaker correction = who SAID the thing (transcript speaker_id)
    - Entity linking = who the claim is ABOUT (claim subject_entity_id)

    V8: Also writes to claim_entities junction table with link_source='user'.
    Sets review_status to 'user_corrected' so pipeline reruns won't overwrite.
    """
    conn = get_connection()
    try:
        # Verify claim exists
        claim = conn.execute(
            "SELECT * FROM event_claims WHERE id = ?", (link.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        # Verify contact exists
        contact = conn.execute(
            "SELECT canonical_name FROM unified_contacts WHERE id = ?", (link.contact_id,)
        ).fetchone()
        if not contact:
            raise HTTPException(404, "Contact not found")

        claim_dict_pre = dict(claim)
        old_subject = claim_dict_pre.get("subject_name", "")

        # Capture old entity's canonical name BEFORE sync changes it
        old_entity_canonical = None
        old_entity_id = claim_dict_pre.get("subject_entity_id")
        if old_entity_id:
            old_contact = conn.execute(
                "SELECT canonical_name FROM unified_contacts WHERE id = ?",
                (old_entity_id,),
            ).fetchone()
            if old_contact:
                old_entity_canonical = old_contact["canonical_name"]

        # Sync claim_entities + event_claims.subject_entity_id (user source)
        sync_claim_entities_subject(conn, link.claim_id, link.contact_id, contact["canonical_name"], "user")

        # Mark as user_corrected — pipeline reruns will skip
        conn.execute(
            "UPDATE event_claims SET review_status = 'user_corrected' WHERE id = ?",
            (link.claim_id,),
        )

        # Replace standalone first-name refs with confirmed canonical name
        claim_dict = dict(claim)
        claim_text = claim_dict.get("claim_text") or ""
        canonical = contact["canonical_name"]

        # ── TEXT REPLACEMENT GUARDS ──
        skip_replacement = False

        # Guard 1: Skip if canonical name already appears in claim text
        if canonical.lower() in claim_text.lower():
            skip_replacement = True

        # Guard 2: Skip if user manually edited this claim's text
        if claim_dict_pre.get("text_user_edited"):
            skip_replacement = True

        text_updated = False
        updated_text = None

        if not skip_replacement:
            # Check for other entities in this claim
            other_entities = conn.execute(
                """SELECT DISTINCT entity_name FROM claim_entities
                   WHERE claim_id = ? AND entity_name != ?""",
                (link.claim_id, canonical),
            ).fetchall()
            other_names = [r["entity_name"] for r in other_entities]
            target = claim_dict.get("target_entity")
            if target:
                other_names.append(target)

            # Use old_entity_canonical (captured BEFORE sync) for name replacement
            replace_from = old_entity_canonical or old_subject
            # Try full-name replacement first (e.g., "Stephen Andrews" -> "Stephen Weber")
            if replace_from and replace_from != canonical:
                direct_replacement = replace_name_in_text(claim_text, replace_from, canonical)
                if direct_replacement and direct_replacement != claim_text:
                    updated_text = direct_replacement
            # Fall back to first-name -> full-name replacement
            if updated_text is None or updated_text == claim_text:
                updated_text = replace_confirmed_name(claim_text, canonical, other_names)

            # Guard 3: Post-replacement sanity check — detect name duplication
            if updated_text and updated_text != claim_text:
                all_entity_names = [canonical] + other_names
                for ename in all_entity_names:
                    if not ename:
                        continue
                    old_count = claim_text.lower().count(ename.lower())
                    new_count = updated_text.lower().count(ename.lower())
                    if new_count > old_count + 1:
                        logger.warning(
                            f"Text replacement guard triggered for claim {link.claim_id}: "
                            f"'{ename}' appears {new_count}x in new text vs {old_count}x in old. "
                            f"Keeping original text."
                        )
                        updated_text = None
                        break

            if updated_text is not None and updated_text != claim_text:
                conn.execute(
                    "UPDATE event_claims SET claim_text = ?, display_overrides = NULL WHERE id = ?",
                    (updated_text, link.claim_id),
                )
                text_updated = True

        # Log correction event
        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, claim_id, error_type, old_value, new_value,
                user_feedback, correction_source)
               VALUES (?, ?, ?, 'bad_entity_linking', ?, ?, ?, 'manual_ui')""",
            (event_id, link.conversation_id, link.claim_id,
             old_subject, canonical, link.user_feedback),
        )

        # Learn alias: add the original extracted name as alias for the linked contact
        if old_subject and old_subject.strip():
            try:
                from sauron.extraction.alias_learner import learn_alias
                learn_alias(conn, link.contact_id, old_subject, canonical)
            except Exception:
                pass  # Non-fatal

        # Detect relational reference in claim text
        relational_ref = None
        claim_text_final = updated_text if text_updated else claim_text
        # Get all entity names in this claim as potential anchors
        all_entities = conn.execute(
            "SELECT DISTINCT entity_name FROM claim_entities WHERE claim_id = ?",
            (link.claim_id,),
        ).fetchall()
        anchor_names = [r["entity_name"] for r in all_entities if r["entity_name"] != canonical]
        # Also check speaker as anchor
        claim_d = dict(claim)
        speaker_name = claim_d.get("speaker") or ""
        if speaker_name and speaker_name not in anchor_names:
            anchor_names.append(speaker_name)

        relational_ref = _detect_relational_reference(claim_text_final, anchor_names)

        # Load full entities list for this claim to return to frontend
        entities_rows = conn.execute(
            """SELECT ce.*, uc.canonical_name as contact_name
               FROM claim_entities ce
               LEFT JOIN unified_contacts uc ON ce.entity_id = uc.id
               WHERE ce.claim_id = ?""",
            (link.claim_id,),
        ).fetchall()
        entities = [dict(e) for e in entities_rows]

        conn.commit()
        return {
            "status": "ok",
            "event_id": event_id,
            "linked_to": canonical,
            "text_updated": text_updated,
            "updated_text": updated_text if text_updated else None,
            "relational_ref": relational_ref,
            "entities": entities,
        }
    finally:
        conn.close()


@router.delete("/entity-link/{link_id}")
def remove_entity_link(link_id: str):
    """Remove an entity link from the claim_entities junction table.

    Also syncs event_claims.subject_entity_id if the removed link was the subject.
    """
    conn = get_connection()
    try:
        # Find the link
        link = conn.execute(
            "SELECT * FROM claim_entities WHERE id = ?", (link_id,)
        ).fetchone()
        if not link:
            raise HTTPException(404, "Entity link not found")

        link_dict = dict(link)
        claim_id = link_dict["claim_id"]
        role = link_dict["role"]

        # Delete the link
        conn.execute("DELETE FROM claim_entities WHERE id = ?", (link_id,))

        # If this was a subject link, check if there are other subject links
        if role == "subject":
            remaining = conn.execute(
                "SELECT entity_id, entity_name FROM claim_entities WHERE claim_id = ? AND role = 'subject'",
                (claim_id,),
            ).fetchone()

            if remaining:
                # Update event_claims to point to remaining subject
                conn.execute(
                    "UPDATE event_claims SET subject_entity_id = ?, subject_name = ? WHERE id = ?",
                    (remaining["entity_id"], remaining["entity_name"], claim_id),
                )
            else:
                # No more subject entities - clear event_claims
                conn.execute(
                    "UPDATE event_claims SET subject_entity_id = NULL WHERE id = ?",
                    (claim_id,),
                )

        conn.commit()
        return {"status": "ok", "removed_link_id": link_id}
    finally:
        conn.close()




class SaveRelationshipRequest(BaseModel):
    """Save a learned relationship to a contact's relationships JSON."""
    anchor_contact_id: str
    relationship: str  # e.g., "son", "wife", "brother"
    target_contact_id: str
    target_name: str
    notes: Optional[str] = None


@router.post("/save-relationship")
def save_relationship(req: SaveRelationshipRequest):
    """Save a relationship to the anchor contact's relationships JSON.

    After a user manually resolves a relational reference (e.g., links
    "Stephen Weber's son" to a contact), this endpoint stores the
    relationship so the relational resolver can auto-resolve it next time.
    """
    conn = get_connection()
    try:
        # Verify anchor contact exists
        anchor = conn.execute(
            "SELECT id, canonical_name, relationships FROM unified_contacts WHERE id = ?",
            (req.anchor_contact_id,),
        ).fetchone()
        if not anchor:
            raise HTTPException(404, "Anchor contact not found")

        # Verify target contact exists
        target = conn.execute(
            "SELECT id, canonical_name FROM unified_contacts WHERE id = ?",
            (req.target_contact_id,),
        ).fetchone()
        if not target:
            raise HTTPException(404, "Target contact not found")

        anchor_dict = dict(anchor)
        target_dict = dict(target)

        # Parse existing relationships JSON
        rels_json = anchor_dict.get("relationships") or "{}"
        try:
            rels = json.loads(rels_json)
        except (json.JSONDecodeError, TypeError):
            rels = {}

        # Add/update the relationship
        # Format: {"son": "contact-id-xxx", "wife": "contact-id-yyy"}
        relationship_key = req.relationship.lower().strip()
        # Plurals stay as-is (sons = sons, not normalized to son)
        rels[relationship_key] = req.target_contact_id

        # Also add a human-readable version for the resolver
        if "learned_relationships" not in rels:
            rels["learned_relationships"] = []
        learned = rels["learned_relationships"]
        entry = {
            "relationship": relationship_key,
            "contact_id": req.target_contact_id,
            "contact_name": req.target_name,
        }
        if req.notes:
            entry["notes"] = req.notes
        # Don't duplicate
        if not any(lr.get("contact_id") == req.target_contact_id and lr.get("relationship") == relationship_key for lr in learned):
            learned.append(entry)

        conn.execute(
            "UPDATE unified_contacts SET relationships = ? WHERE id = ?",
            (json.dumps(rels), req.anchor_contact_id),
        )

        conn.commit()

        # Log for debugging (Bug 6 verification)
        logger.info(
            f"Saved relationship: {anchor_dict['canonical_name']} -> "
            f"{relationship_key} -> {target_dict['canonical_name']} "
            f"(anchor={req.anchor_contact_id[:8]}, target={req.target_contact_id[:8]})"
        )
        logger.info(f"Updated relationships JSON: {json.dumps(rels)[:200]}")

        return {
            "status": "ok",
            "anchor": anchor_dict["canonical_name"],
            "relationship": relationship_key,
            "target": target_dict["canonical_name"],
        }
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════
# CLAIM APPROVAL ENDPOINTS
# ═══════════════════════════════════════════════════════

class ApproveClaimRequest(BaseModel):
    conversation_id: str
    claim_id: str


class ApproveClaimsBulkRequest(BaseModel):
    conversation_id: str
    claim_ids: list[str]


class DeferClaimRequest(BaseModel):
    conversation_id: str
    claim_id: str
    reason: Optional[str] = None


class DismissClaimRequest(BaseModel):
    conversation_id: str
    claim_id: str
    error_type: str
    user_feedback: Optional[str] = None


class CommitmentMetaRequest(BaseModel):
    conversation_id: str
    claim_id: str
    firmness: Optional[str] = None
    direction: Optional[str] = None
    has_specific_action: Optional[bool] = None
    has_deadline: Optional[bool] = None
    has_condition: Optional[bool] = None
    condition_text: Optional[str] = None
    time_horizon: Optional[str] = None



# Field -> error_type mapping for batch corrections
FIELD_ERROR_MAP = {
    "firmness": "wrong_commitment_firmness",
    "direction": "wrong_commitment_direction",
    "has_deadline": "wrong_commitment_deadline",
    "time_horizon": "wrong_commitment_deadline",
    "has_condition": "wrong_commitment_condition",
    "condition_text": "wrong_commitment_condition",
    "has_specific_action": "wrong_commitment_action",
    "claim_type": "wrong_claim_type",
    "confidence": "wrong_confidence",
    "modality": "wrong_modality",
    "polarity": "wrong_polarity",
    "stability": "wrong_stability",
    "claim_text": "claim_text_edited",
}

# Columns that can be batch-edited
BATCH_EDITABLE_COLUMNS = {
    "firmness", "direction", "has_deadline", "time_horizon",
    "has_condition", "condition_text", "has_specific_action",
    "claim_type", "confidence", "modality", "polarity", "stability",
    "claim_text",
}


@router.post("/claim-batch")
def correct_claim_batch(correction: BatchClaimCorrection):
    """Batch-correct multiple fields on a single claim in one save.

    Writes individual correction_events per changed field for granular learning,
    but applies all changes atomically in a single transaction.
    """
    conn = get_connection()
    try:
        # Read current claim state
        claim = conn.execute(
            "SELECT * FROM event_claims WHERE id = ?",
            (correction.claim_id,),
        ).fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")

        # Filter to only changed fields
        updates = {}
        events = []
        for field, new_val in correction.corrections.items():
            if field not in BATCH_EDITABLE_COLUMNS:
                continue
            old_val = claim[field] if field in claim.keys() else None
            # Normalize for comparison
            if isinstance(new_val, bool):
                old_comparable = bool(old_val) if old_val is not None else False
            elif isinstance(new_val, (int, float)):
                try:
                    old_comparable = float(old_val) if old_val is not None else None
                    new_val_comparable = float(new_val)
                except (ValueError, TypeError):
                    old_comparable = old_val
                    new_val_comparable = new_val
            else:
                old_comparable = old_val
                new_val_comparable = new_val

            if str(old_val) != str(new_val):
                updates[field] = new_val
                error_type = FIELD_ERROR_MAP.get(field, "bad_commitment_extraction")
                events.append({
                    "error_type": error_type,
                    "old_value": str(old_val) if old_val is not None else None,
                    "new_value": str(new_val),
                })

        if not updates:
            return {"status": "ok", "message": "No changes detected", "claim_id": correction.claim_id}

        # Apply all column updates in one statement
        set_clauses = ", ".join(f"{col} = ?" for col in updates.keys())
        values = list(updates.values()) + [correction.claim_id]
        conn.execute(
            f"UPDATE event_claims SET {set_clauses} WHERE id = ?",
            values,
        )

        # Mark text as user-edited if claim_text was changed
        if "claim_text" in updates:
            conn.execute(
                "UPDATE event_claims SET text_user_edited = 1 WHERE id = ?",
                (correction.claim_id,),
            )

        # Set review_status
        conn.execute(
            "UPDATE event_claims SET review_status = 'user_corrected' WHERE id = ?",
            (correction.claim_id,),
        )

        # Log individual correction_events for learning
        event_ids = []
        for evt in events:
            event_id = str(uuid.uuid4())
            event_ids.append(event_id)
            conn.execute(
                """INSERT INTO correction_events
                   (id, conversation_id, claim_id, error_type, old_value, new_value,
                    user_feedback, correction_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'manual_ui')""",
                (event_id, correction.conversation_id, correction.claim_id,
                 evt["error_type"], evt["old_value"], evt["new_value"],
                 correction.user_feedback),
            )

        # Cascade to beliefs (same pattern as correct_claim)
        _affected = conn.execute(
            """SELECT DISTINCT b.id, b.status FROM beliefs b
               JOIN belief_evidence be ON be.belief_id = b.id
               WHERE be.claim_id = ? AND b.status != 'under_review'""",
            (correction.claim_id,),
        ).fetchall()
        if _affected:
            conn.execute(
                """UPDATE beliefs SET status = 'under_review'
                   WHERE id IN (
                       SELECT DISTINCT be.belief_id FROM belief_evidence be
                       WHERE be.claim_id = ?
                   )""",
                (correction.claim_id,),
            )
            primary_event_id = event_ids[0] if event_ids else str(uuid.uuid4())
            for ab in _affected:
                conn.execute(
                    """INSERT INTO belief_transitions
                       (id, belief_id, old_status, new_status, driver, source_correction_id)
                       VALUES (?, ?, ?, 'under_review', 'correction', ?)""",
                    (str(uuid.uuid4()), ab["id"], ab["status"], primary_event_id),
                )

            # Queue re-synthesis for affected beliefs (Feature 1)
            for ab in _affected:
                try:
                    from sauron.learning.resynthesize import queue_resynthesis
                    queue_resynthesis(ab["id"], primary_event_id)
                except Exception:
                    logger.exception("Failed to queue belief re-synthesis")

        conn.commit()

        # Check dynamic analysis trigger (Feature 6)
        _check_dynamic_trigger(conn)

        # Return updated claim
        updated = conn.execute(
            "SELECT * FROM event_claims WHERE id = ?",
            (correction.claim_id,),
        ).fetchone()

        return {
            "status": "ok",
            "claim_id": correction.claim_id,
            "corrections_applied": len(updates),
            "events_logged": len(events),
            "review_status": "user_corrected",
            "updated_fields": list(updates.keys()),
            "claim": dict(updated) if updated else None,
        }
    finally:
        conn.close()



@router.post("/add-claim")
def add_claim(req: AddClaimRequest):
    """Create a new user-authored claim.

    If subject_entity_id is provided (from autocomplete), uses it directly.
    If only subject_name is provided, attempts entity resolution.
    """
    conn = get_connection()
    try:
        claim_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())

        # Resolve entity if needed
        entity_id = req.subject_entity_id
        entity_name = req.subject_name
        if not entity_id and entity_name:
            # Try direct name lookup in unified_contacts
            try:
                match = conn.execute(
                    """SELECT id, display_name FROM unified_contacts
                       WHERE LOWER(display_name) = LOWER(?)
                       OR LOWER(display_name) LIKE LOWER(? || ' %')
                       LIMIT 1""",
                    (entity_name, entity_name),
                ).fetchone()
                if match:
                    entity_id = match["id"]
                    entity_name = match["display_name"]
            except Exception as e:
                logger.warning(f"Entity lookup failed for '{entity_name}': {e}")

        # Insert claim
        conn.execute(
            """INSERT INTO event_claims
               (id, conversation_id, episode_id, claim_type, claim_text,
                subject_entity_id, subject_name, confidence, review_status,
                text_user_edited, firmness, direction, has_specific_action,
                has_deadline, time_horizon, has_condition, condition_text,
                evidence_quote, importance)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, 'user_corrected', 1,
                       ?, ?, ?, ?, ?, ?, ?, ?, 0.5)""",
            (claim_id, req.conversation_id, req.episode_id, req.claim_type,
             req.claim_text, entity_id, entity_name,
             req.firmness, req.direction, req.has_specific_action,
             req.has_deadline, req.time_horizon, req.has_condition,
             req.condition_text, req.evidence_quote),
        )

        # Insert entity junction if resolved
        if entity_id:
            conn.execute(
                """INSERT INTO claim_entities (id, claim_id, contact_id, role, link_source)
                   VALUES (?, ?, ?, 'subject', 'user')""",
                (str(uuid.uuid4()), claim_id, entity_id),
            )

        # Log correction event
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, claim_id, error_type, new_value,
                user_feedback, correction_source)
               VALUES (?, ?, ?, 'missed_claim', ?, 'User-created claim', 'manual_ui')""",
            (event_id, req.conversation_id, claim_id, req.claim_text),
        )

        conn.commit()

        # Return created claim with entity data
        created = conn.execute(
            """SELECT ec.*, uc.display_name as linked_entity_name
               FROM event_claims ec
               LEFT JOIN claim_entities ce ON ce.claim_id = ec.id AND ce.role = 'subject'
               LEFT JOIN unified_contacts uc ON uc.id = ce.contact_id
               WHERE ec.id = ?""",
            (claim_id,),
        ).fetchone()

        result = dict(created) if created else {"id": claim_id}
        # Build entities array for frontend
        entities = conn.execute(
            "SELECT id, contact_id, role, link_source FROM claim_entities WHERE claim_id = ?",
            (claim_id,),
        ).fetchall()
        result["entities"] = [dict(e) for e in entities]

        return {"status": "ok", "claim_id": claim_id, "claim": result}
    finally:
        conn.close()


@router.patch("/reassign-claim")
def reassign_claim(req: ReassignClaimRequest):
    """Reassign a claim to a different episode (or make it an orphan)."""
    conn = get_connection()
    try:
        event_id = str(uuid.uuid4())

        # Get old episode_id
        old = conn.execute(
            "SELECT episode_id FROM event_claims WHERE id = ?",
            (req.claim_id,),
        ).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Claim not found")
        old_episode = old["episode_id"]

        # Update episode_id
        conn.execute(
            "UPDATE event_claims SET episode_id = ? WHERE id = ?",
            (req.episode_id, req.claim_id),
        )

        # Log correction event
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, claim_id, error_type, old_value, new_value,
                correction_source)
               VALUES (?, ?, ?, 'bad_episode_segmentation', ?, ?, 'manual_ui')""",
            (event_id, req.conversation_id, req.claim_id,
             old_episode, req.episode_id),
        )

        conn.commit()
        return {"status": "ok", "claim_id": req.claim_id, "new_episode_id": req.episode_id}
    finally:
        conn.close()


@router.post("/approve-claim")
def approve_claim(req: ApproveClaimRequest):
    """Mark a claim as approved (persists to DB)."""
    conn = get_connection()
    try:
        claim = conn.execute(
            "SELECT id, review_status FROM event_claims WHERE id = ?", (req.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        conn.execute(
            "UPDATE event_claims SET review_status = 'user_confirmed' WHERE id = ?",
            (req.claim_id,),
        )
        conn.commit()
        return {"status": "ok", "claim_id": req.claim_id, "review_status": "user_confirmed"}
    finally:
        conn.close()


@router.post("/approve-claims-bulk")
def approve_claims_bulk(req: ApproveClaimsBulkRequest):
    """Mark multiple claims as approved in one call."""
    conn = get_connection()
    try:
        updated = 0
        for claim_id in req.claim_ids:
            conn.execute(
                "UPDATE event_claims SET review_status = 'user_confirmed' WHERE id = ?",
                (claim_id,),
            )
            updated += 1
        conn.commit()
        return {"status": "ok", "updated": updated}
    finally:
        conn.close()


@router.post("/defer-claim")
def defer_claim(req: DeferClaimRequest):
    """Defer a claim for later review."""
    conn = get_connection()
    try:
        claim = conn.execute(
            "SELECT id FROM event_claims WHERE id = ?", (req.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        conn.execute(
            "UPDATE event_claims SET review_status = 'deferred' WHERE id = ?",
            (req.claim_id,),
        )

        if req.reason:
            conn.execute(
                """INSERT INTO correction_events
                   (id, conversation_id, claim_id, error_type, old_value, new_value,
                    user_feedback, correction_source)
                   VALUES (?, ?, ?, 'claim_text_edited', NULL, 'deferred', ?, 'manual_ui')""",
                (str(uuid.uuid4()), req.conversation_id, req.claim_id, req.reason),
            )

        conn.commit()
        return {"status": "ok", "claim_id": req.claim_id, "review_status": "deferred"}
    finally:
        conn.close()


@router.post("/dismiss-claim")
def dismiss_claim(req: DismissClaimRequest):
    """Dismiss a claim — set confidence=0, append [DISMISSED], mark beliefs under_review."""
    conn = get_connection()
    try:
        claim = conn.execute(
            "SELECT id, claim_text FROM event_claims WHERE id = ?", (req.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        # Dismiss: confidence=0, append [DISMISSED], review_status='dismissed'
        conn.execute(
            "UPDATE event_claims SET confidence = 0, claim_text = claim_text || ' [DISMISSED]', review_status = 'dismissed' WHERE id = ?",
            (req.claim_id,),
        )

        # Log correction event
        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, claim_id, error_type, old_value, new_value,
                user_feedback, correction_source)
               VALUES (?, ?, ?, ?, ?, 'dismissed', ?, 'manual_ui')""",
            (event_id, req.conversation_id, req.claim_id, req.error_type,
             claim["claim_text"], req.user_feedback),
        )

        # Mark supporting beliefs as under_review
        _affected = conn.execute(
            """SELECT DISTINCT b.id, b.status FROM beliefs b
               JOIN belief_evidence be ON be.belief_id = b.id
               WHERE be.claim_id = ? AND b.status != 'under_review'""",
            (req.claim_id,),
        ).fetchall()
        conn.execute(
            """UPDATE beliefs SET status = 'under_review'
               WHERE id IN (
                   SELECT DISTINCT be.belief_id FROM belief_evidence be
                   WHERE be.claim_id = ?
               )""",
            (req.claim_id,),
        )
        for _ab in _affected:
            conn.execute(
                """INSERT INTO belief_transitions
                   (id, belief_id, old_status, new_status, driver, source_correction_id)
                   VALUES (?, ?, ?, 'under_review', 'correction', ?)""",
                (str(uuid.uuid4()), _ab["id"], _ab["status"], event_id),
            )

        conn.commit()
        return {"status": "ok", "claim_id": req.claim_id, "review_status": "dismissed", "error_type": req.error_type}
    finally:
        conn.close()


@router.post("/commitment-meta")
def update_commitment_meta(req: CommitmentMetaRequest):
    """Update commitment classification metadata on a claim."""
    conn = get_connection()
    try:
        claim = conn.execute(
            "SELECT * FROM event_claims WHERE id = ?", (req.claim_id,)
        ).fetchone()
        if not claim:
            raise HTTPException(404, "Claim not found")

        claim_dict = dict(claim)
        updates = []
        params = []

        if req.firmness is not None:
            old_firmness = claim_dict.get("firmness")
            updates.append("firmness = ?")
            params.append(req.firmness)
            # Log firmness change as correction event
            if old_firmness != req.firmness:
                conn.execute(
                    """INSERT INTO correction_events
                       (id, conversation_id, claim_id, error_type, old_value, new_value,
                        correction_source)
                       VALUES (?, ?, ?, 'wrong_commitment_firmness', ?, ?, 'manual_ui')""",
                    (str(uuid.uuid4()), req.conversation_id, req.claim_id,
                     old_firmness, req.firmness),
                )

        if req.direction is not None:
            updates.append("direction = ?")
            params.append(req.direction)
        if req.has_specific_action is not None:
            updates.append("has_specific_action = ?")
            params.append(req.has_specific_action)
        if req.has_deadline is not None:
            updates.append("has_deadline = ?")
            params.append(req.has_deadline)
        if req.has_condition is not None:
            updates.append("has_condition = ?")
            params.append(req.has_condition)
        if req.condition_text is not None:
            updates.append("condition_text = ?")
            params.append(req.condition_text)
        if req.time_horizon is not None:
            updates.append("time_horizon = ?")
            params.append(req.time_horizon)

        if updates:
            params.append(req.claim_id)
            conn.execute(
                f"UPDATE event_claims SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()

        return {"status": "ok", "claim_id": req.claim_id}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# SPEAKER CASCADE TO CLAIMS
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# VOICE ENROLLMENT
# ═══════════════════════════════════════════════════════

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


# Legacy endpoint for backwards compat
class ExtractionCorrection(BaseModel):
    conversation_id: str
    correction_type: str
    original_value: Optional[str] = None
    corrected_value: str


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


# =====================================================
# PIPELINE REDESIGN: SPEAKER MERGE + SEGMENT REASSIGN
# =====================================================

class MergeSpeakersRequest(BaseModel):
    conversation_id: str
    from_label: str
    to_label: str


class ReassignSegmentRequest(BaseModel):
    transcript_segment_id: str
    new_speaker_label: str


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
