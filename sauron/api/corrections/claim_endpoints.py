"""Claim correction endpoints — event logging, claim edit, entity link, batch, add, reassign."""
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException

from sauron.db.connection import get_connection
from sauron.api.entity_helpers import replace_confirmed_name, replace_name_in_text
from sauron.api.corrections.models import (
    ERROR_TYPES, FIELD_ERROR_MAP, BATCH_EDITABLE_COLUMNS,
    FAST_GENERALIZE,
    CorrectionEvent, ClaimCorrection, BatchClaimCorrection,
    AddClaimRequest, ReassignClaimRequest, EntityLink, SaveRelationshipRequest,
)
from sauron.api.corrections.helpers import (
    _check_dynamic_trigger, _detect_relational_reference,
    sync_claim_entities_subject,
)

logger = logging.getLogger(__name__)
router = APIRouter()


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
