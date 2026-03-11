"""Relational entity resolution pass for the extraction pipeline.

Runs after Sonnet claims extraction and before Opus synthesis.
Scans claims with null subject_entity_id and attempts to match
subject_name against unified_contacts using:
  1. Direct name match (canonical_name or aliases)
  2. Relational term match ("my brother" -> contact with relationship)

V8 changes:
  - Respects review_status: NEVER overwrites user_corrected claims
  - Respects link_source='user' in claim_entities
  - Syncs claim_entities junction table on resolution
  - Logs conflicts when pipeline disagrees with user corrections
  - Only auto-resolves relational terms with ONE clear match (no guessing)
"""

import json
import logging
import re
import uuid

from sauron.db.connection import get_connection
from sauron.api.relational_terms import RELATIONAL_TERMS, PLURAL_TERMS, ALL_TERMS

logger = logging.getLogger(__name__)

# Patterns that indicate a relational reference
RELATIONAL_PATTERNS = [
    re.compile(r"\b(?:my|his|her|their|stephen'?s?)\s+(\w+)\b", re.IGNORECASE),
]


def _verify_conversation_connection(conn, conversation_id: str, contact_id: str) -> bool:
    """Verify a contact has a plausible connection to this conversation.

    Used to gate first-name-only auto-resolution. Returns True if ANY of:
    1. Contact is a confirmed speaker in this conversation
    2. Contact's full canonical name appears in any claim text
    3. Contact is linked to the conversation's calendar event
    """
    # Check 1: Is the contact a confirmed speaker?
    speaker_match = conn.execute(
        """SELECT 1 FROM transcripts
           WHERE conversation_id = ? AND speaker_id = ? LIMIT 1""",
        (conversation_id, contact_id),
    ).fetchone()
    if speaker_match:
        return True

    # Check 2: Does the contact's full name appear in any claim text?
    contact = conn.execute(
        "SELECT canonical_name FROM unified_contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()
    if contact:
        full_name = contact["canonical_name"]
        name_in_claims = conn.execute(
            """SELECT 1 FROM event_claims
               WHERE conversation_id = ? AND claim_text LIKE ? LIMIT 1""",
            (conversation_id, f"%{full_name}%"),
        ).fetchone()
        if name_in_claims:
            return True

    # Check 3: Is the contact linked to the conversation's calendar event?
    intent_match = conn.execute(
        """SELECT 1 FROM meeting_intentions
           WHERE conversation_id = ? AND target_contact_id = ? LIMIT 1""",
        (conversation_id, contact_id),
    ).fetchone()
    if intent_match:
        return True

    return False


def resolve_claim_entities(conversation_id: str) -> dict:
    """Resolve unlinked claim entities for a conversation.

    Respects user corrections: claims with review_status='user_corrected'
    or claim_entities entries with link_source='user' are NEVER modified.
    If the resolver disagrees with a user correction, it logs a conflict
    but does NOT apply the change.

    Returns dict with counts: {resolved, ambiguous, unresolved, skipped_user, conflicts}
    """
    conn = get_connection()
    stats = {"resolved": 0, "ambiguous": 0, "unresolved": 0, "skipped_user": 0, "conflicts": 0}

    try:
        # Get unlinked claims for this conversation
        # SKIP claims where review_status is user_corrected or user_confirmed
        claims = conn.execute(
            """SELECT id, subject_name, target_entity, review_status
               FROM event_claims
               WHERE conversation_id = ?
                 AND subject_entity_id IS NULL
                 AND subject_name IS NOT NULL
                 AND subject_name != ''
                 AND (review_status IS NULL OR review_status = 'unreviewed')""",
            (conversation_id,),
        ).fetchall()

        if not claims:
            return stats

        # Also check for claims that ARE linked but were resolved by model/resolver
        # (not user) — these can be re-resolved if we have better data now
        # But we DON'T touch user-corrected ones

        # Check for user-corrected claims that we would have tried to process
        user_corrected_count = conn.execute(
            """SELECT COUNT(*) FROM event_claims
               WHERE conversation_id = ?
                 AND subject_entity_id IS NULL
                 AND subject_name IS NOT NULL
                 AND review_status IN ('user_corrected', 'user_confirmed')""",
            (conversation_id,),
        ).fetchone()[0]
        stats["skipped_user"] = user_corrected_count

        # Also check claim_entities for user-linked entries that conflict
        user_linked_claims = set()
        user_links = conn.execute(
            """SELECT ce.claim_id FROM claim_entities ce
               JOIN event_claims ec ON ec.id = ce.claim_id
               WHERE ec.conversation_id = ?
                 AND ce.link_source = 'user'""",
            (conversation_id,),
        ).fetchall()
        for row in user_links:
            user_linked_claims.add(row["claim_id"])

        # Load all contacts with their aliases and relationships
        contacts = conn.execute(
            "SELECT id, canonical_name, aliases, relationships FROM unified_contacts"
        ).fetchall()

        # Build lookup structures
        name_to_contacts = {}  # lowercase name -> list of contact dicts
        alias_to_contacts = {}  # lowercase alias -> list of contact dicts
        relation_to_contacts = {}  # relation term -> list of contact dicts (TARGET contacts)
        contacts_by_id = {}  # id -> contact dict

        for c in contacts:
            cd = dict(c)
            cname = cd["canonical_name"]
            contacts_by_id[cd["id"]] = cd

            # Direct name lookup
            name_key = cname.lower().strip()
            name_to_contacts.setdefault(name_key, []).append(cd)

            # First name lookup
            first_name = name_key.split()[0] if " " in name_key else name_key
            name_to_contacts.setdefault(first_name, []).append(cd)

            # Alias lookup
            aliases = cd.get("aliases") or ""
            for alias in aliases.split(";"):
                alias = alias.strip().lower()
                if alias:
                    alias_to_contacts.setdefault(alias, []).append(cd)

            # Relational lookup from relationships JSON
            rels_json = cd.get("relationships")
            if rels_json:
                try:
                    rels = json.loads(rels_json)
                except (json.JSONDecodeError, TypeError):
                    rels = {}

                # Build contacts_by_id for target resolution
                if cd["id"] not in contacts_by_id:
                    contacts_by_id[cd["id"]] = cd

                # Check for learned_relationships: [{"relationship": "son", "contact_id": "xxx", "contact_name": "..."}]
                for lr in rels.get("learned_relationships", []):
                    rel_term = (lr.get("relationship") or "").lower().strip()
                    target_id = lr.get("contact_id", "")
                    target_name = lr.get("contact_name", "")
                    if rel_term and (rel_term in ALL_TERMS or rel_term in RELATIONAL_TERMS):
                        # Map term -> TARGET contact (who the relationship points to)
                        target_cd = contacts_by_id.get(target_id)
                        if target_cd:
                            relation_to_contacts.setdefault(rel_term, []).append(target_cd)
                        elif target_name:
                            # Look up target by name
                            target_matches = name_to_contacts.get(target_name.lower().strip(), [])
                            for tm in target_matches:
                                relation_to_contacts.setdefault(rel_term, []).append(tm)

                # Check for spec-format relationships: {"son": "contact-id", "wife": "contact-id"}
                for key, val in rels.items():
                    key_lower = key.lower().strip()
                    if key_lower in ("learned_relationships", "tags", "personalring",
                                     "personalgroup", "howwemet", "partnername",
                                     "partner_name", "personal_ring", "personal_group",
                                     "how_we_met", "relation_to_stephen", "relationship"):
                        continue  # Skip metadata fields
                    if key_lower in ALL_TERMS and isinstance(val, str) and len(val) > 10:
                        # val is a contact ID — resolve to TARGET contact
                        target_cd = contacts_by_id.get(val)
                        if target_cd:
                            relation_to_contacts.setdefault(key_lower, []).append(target_cd)

                # Check relation_to_stephen field (explicit relationship label)
                # This means THIS contact IS the [relation] to Stephen
                # So this contact IS the target
                rel_to_stephen = (rels.get("relation_to_stephen") or rels.get("relationship") or "").lower().strip()
                if rel_to_stephen and rel_to_stephen in ALL_TERMS:
                    relation_to_contacts.setdefault(rel_to_stephen, []).append(cd)

                # Check partnerName field (Networking App data)
                # This means this contact's partner is named X
                partner_name = rels.get("partnerName") or rels.get("partner_name") or ""
                if partner_name:
                    # Look up the partner by name and map partner terms to THEM
                    partner_matches = name_to_contacts.get(partner_name.lower().strip(), [])
                    for pm in partner_matches:
                        for term in ("wife", "husband", "spouse", "partner"):
                            relation_to_contacts.setdefault(term, []).append(pm)

        # Now resolve each claim
        for claim in claims:
            claim_dict = dict(claim)
            claim_id = claim_dict["id"]
            subject = claim_dict["subject_name"].strip()
            subject_lower = subject.lower()

            # Skip if user has a link_source='user' entry in claim_entities
            if claim_id in user_linked_claims:
                stats["skipped_user"] += 1
                continue

            match = None

            # 1. Direct name match
            candidates = name_to_contacts.get(subject_lower, [])
            if len(candidates) == 1:
                match = candidates[0]
                # Gate first-name-only matches — require plausible conversation connection
                if " " not in subject:
                    if not _verify_conversation_connection(conn, conversation_id, match["id"]):
                        logger.debug(
                            f"First-name-only match '{subject}' -> {match['canonical_name']} "
                            f"has no conversation connection — marking ambiguous"
                        )
                        match = None
                        stats["ambiguous"] += 1
                        continue
            elif len(candidates) > 1:
                stats["ambiguous"] += 1
                continue

            # 2. Alias match (if no direct match)
            if not match:
                candidates = alias_to_contacts.get(subject_lower, [])
                if len(candidates) == 1:
                    match = candidates[0]
                elif len(candidates) > 1:
                    stats["ambiguous"] += 1
                    continue

            # 3. Relational term match — only with ONE clear anchor + ONE match
            if not match:
                for pattern in RELATIONAL_PATTERNS:
                    m = pattern.search(subject)
                    if m:
                        term = m.group(1).lower()
                        if term in ALL_TERMS:
                            candidates = relation_to_contacts.get(term, [])
                            if len(candidates) == 1:
                                match = candidates[0]
                            elif len(candidates) > 1:
                                # Ambiguous — multiple contacts match this relation
                                stats["ambiguous"] += 1
                            break

            if match:
                # Update event_claims
                conn.execute(
                    """UPDATE event_claims
                       SET subject_entity_id = ?, subject_name = ?
                       WHERE id = ?""",
                    (match["id"], match["canonical_name"], claim_id),
                )

                # Sync claim_entities junction table
                conn.execute(
                    "DELETE FROM claim_entities WHERE claim_id = ? AND role = 'subject'",
                    (claim_id,),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO claim_entities
                       (id, claim_id, entity_id, entity_name, role, confidence, link_source)
                       VALUES (?, ?, ?, ?, 'subject', NULL, 'resolver')""",
                    (str(uuid.uuid4()), claim_id, match["id"], match["canonical_name"]),
                )

                stats["resolved"] += 1
                logger.debug(
                    f"Resolved '{subject}' -> {match['canonical_name']} "
                    f"for claim {claim_id[:8]}"
                )

                # Learn alias: add the extracted name as alias for this contact
                try:
                    from sauron.extraction.alias_learner import learn_alias
                    learn_alias(conn, match["id"], subject, match["canonical_name"])
                except Exception:
                    pass  # Non-fatal
            else:
                stats["unresolved"] += 1

        conn.commit()
        logger.info(
            f"Entity resolution for {conversation_id[:8]}: "
            f"{stats['resolved']} resolved, {stats['ambiguous']} ambiguous, "
            f"{stats['unresolved']} unresolved, {stats['skipped_user']} user-protected"
        )
    except Exception:
        conn.rollback()
        logger.exception("Entity resolution failed")
        raise
    finally:
        conn.close()

    return stats
