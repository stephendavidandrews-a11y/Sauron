"""Post-synthesis entity auto-linker.

Runs after Opus synthesis completes, before the conversation enters
the review queue. Scans every person reference in synthesis objects
(standing offers, scheduling leads, graph edges, new contacts mentioned)
and attempts to resolve them against known contacts.

Four resolution strategies in priority order:
  1. Exact match on claim_entities.entity_name for this conversation
  2. Match on event_claims.subject_name where subject_entity_id is set
  3. Direct match on unified_contacts canonical_name and aliases
  4. Last-name-only fallback (unique match only)

Unresolved names get provisional contacts created automatically.

See: docs/specs/entity_resolution_review_plan.md, Phase 1.
"""

import logging
import uuid
from typing import Optional

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def link_synthesis_entities(conversation_id: str) -> dict:
    """Auto-link all person references in synthesis objects for a conversation.

    Returns stats dict with counts of resolved, provisional, skipped.
    """
    conn = get_connection()
    try:
        # Load synthesis from the latest pass-3 extraction
        row = conn.execute(
            """SELECT extraction_json FROM extractions
               WHERE conversation_id = ? AND pass_number = 3
               ORDER BY created_at DESC LIMIT 1""",
            (conversation_id,),
        ).fetchone()

        if not row:
            logger.warning(f"[{conversation_id[:8]}] No synthesis extraction found")
            return {"resolved": 0, "provisional": 0, "skipped": 0}

        import json
        synthesis = json.loads(row["extraction_json"])

        # Build lookup caches for this conversation
        claim_entity_map = _build_claim_entity_map(conn, conversation_id)
        claim_subject_map = _build_claim_subject_map(conn, conversation_id)
        contacts_cache = _build_contacts_cache(conn)

        stats = {"resolved": 0, "provisional": 0, "skipped": 0}

        # Collect all person references from synthesis objects
        references = _collect_person_references(synthesis)

        # Deduplicate by original_name (resolve each unique name once)
        unique_names: dict[str, list[dict]] = {}
        for ref in references:
            key = ref["original_name"].strip().lower()
            if key not in unique_names:
                unique_names[key] = []
            unique_names[key].append(ref)

        # Resolve each unique name, then apply to all references
        for name_lower, refs in unique_names.items():
            original_name = refs[0]["original_name"]

            entity_id, method, confidence = _resolve_name(
                original_name,
                claim_entity_map,
                claim_subject_map,
                contacts_cache,
            )

            if entity_id is None:
                # Create provisional contact
                entity_id, method, confidence = _create_provisional_and_link_claims(
                    conn, conversation_id, original_name
                )
                stats["provisional"] += 1
            else:
                stats["resolved"] += 1

                # Learn alias: add resolved name to contact's aliases
                try:
                    canonical = _get_canonical_name(conn, entity_id)
                    if canonical:
                        from sauron.extraction.alias_learner import learn_alias
                        learn_alias(conn, entity_id, original_name, canonical)
                except Exception:
                    pass  # Non-fatal — don't break linking over alias learning

            # Store synthesis_entity_links for all references with this name
            for ref in refs:
                _store_link(
                    conn,
                    conversation_id=conversation_id,
                    object_type=ref["object_type"],
                    object_index=ref["object_index"],
                    field_name=ref["field_name"],
                    original_name=ref["original_name"],
                    resolved_entity_id=entity_id,
                    resolution_method=method,
                    confidence=confidence,
                )

        conn.commit()
        logger.info(
            f"[{conversation_id[:8]}] Synthesis linking: "
            f"{stats['resolved']} resolved, {stats['provisional']} provisional, "
            f"{stats['skipped']} skipped"
        )
        return stats

    except Exception:
        conn.rollback()
        logger.exception(f"[{conversation_id[:8]}] Synthesis linking failed")
        return {"resolved": 0, "provisional": 0, "skipped": 0, "error": True}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# Person reference collection
# ═══════════════════════════════════════════════════════════════

def _collect_person_references(synthesis: dict) -> list[dict]:
    """Extract all person name references from synthesis objects."""
    refs = []

    # Standing offers → contact_name
    for i, offer in enumerate(synthesis.get("standing_offers", [])):
        name = offer.get("contact_name", "").strip()
        if name:
            refs.append({
                "object_type": "standing_offer",
                "object_index": i,
                "field_name": "contact_name",
                "original_name": name,
            })

    # Scheduling leads → contact_name
    for i, lead in enumerate(synthesis.get("scheduling_leads", [])):
        name = lead.get("contact_name", "").strip()
        if name:
            refs.append({
                "object_type": "scheduling_lead",
                "object_index": i,
                "field_name": "contact_name",
                "original_name": name,
            })

    # Graph edges → from_entity, to_entity (person type only)
    for i, edge in enumerate(synthesis.get("graph_edges", [])):
        from_name = edge.get("from_entity", "").strip()
        to_name = edge.get("to_entity", "").strip()
        from_type = edge.get("from_type", "person").lower()
        to_type = edge.get("to_type", "person").lower()
        if from_name and from_type == "person":
            refs.append({
                "object_type": "graph_edge",
                "object_index": i,
                "field_name": "from_entity",
                "original_name": from_name,
            })
        elif from_name:
            logger.debug(f"Skipping non-person graph edge from_entity: '{from_name}' (type={from_type})")
        if to_name and to_type == "person":
            refs.append({
                "object_type": "graph_edge",
                "object_index": i,
                "field_name": "to_entity",
                "original_name": to_name,
            })
        elif to_name:
            logger.debug(f"Skipping non-person graph edge to_entity: '{to_name}' (type={to_type})")

    # New contacts mentioned (from claims pass)
    for i, name in enumerate(synthesis.get("new_contacts_mentioned", [])):
        if isinstance(name, str) and name.strip():
            refs.append({
                "object_type": "new_contact",
                "object_index": i,
                "field_name": "name",
                "original_name": name.strip(),
            })

    return refs


# ═══════════════════════════════════════════════════════════════
# Resolution strategies
# ═══════════════════════════════════════════════════════════════

def _resolve_name(
    name: str,
    claim_entity_map: dict,
    claim_subject_map: dict,
    contacts_cache: list[dict],
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """Try four strategies in order. Returns (entity_id, method, confidence) or (None, None, None)."""

    name_lower = name.strip().lower()

    # Strategy 1: Exact match on claim_entities.entity_name for this conversation
    if name_lower in claim_entity_map:
        entity_id = claim_entity_map[name_lower]
        logger.debug(f"Strategy 1 (claim_entity): '{name}' → {entity_id[:8]}")
        return entity_id, "claim_entity", 0.95

    # Strategy 2: Match on event_claims.subject_name with populated subject_entity_id
    if name_lower in claim_subject_map:
        entity_id = claim_subject_map[name_lower]
        logger.debug(f"Strategy 2 (claim_subject): '{name}' → {entity_id[:8]}")
        return entity_id, "claim_subject", 0.80

    # Strategy 3: Direct match on unified_contacts canonical_name and aliases
    for contact in contacts_cache:
        # Check canonical_name (exact match)
        if contact["canonical_name_lower"] == name_lower:
            logger.debug(f"Strategy 3 (canonical_name): '{name}' → {contact['id'][:8]}")
            return contact["id"], "canonical_name", 0.90

        # Check aliases
        for alias in contact["aliases_list"]:
            if alias.lower() == name_lower:
                # Green if multi-word alias or full canonical name match,
                # yellow if single-word alias
                is_multi_word = len(alias.split()) > 1
                confidence = 0.85 if is_multi_word else 0.60
                method = "alias" if is_multi_word else "alias_single_word"
                logger.debug(f"Strategy 3 ({method}): '{name}' → {contact['id'][:8]}")
                return contact["id"], method, confidence

    # Strategy 4: Last-name fallback (unique match only)
    words = name.split()
    if len(words) >= 2:
        last_name = words[-1].lower()
        matches = []
        for contact in contacts_cache:
            contact_words = contact["canonical_name_lower"].split()
            if contact_words and contact_words[-1] == last_name:
                matches.append(contact)
        if len(matches) == 1:
            entity_id = matches[0]["id"]
            logger.debug(f"Strategy 4 (last_name): '{name}' → {entity_id[:8]}")
            return entity_id, "last_name", 0.55
        elif len(matches) > 1:
            logger.debug(
                f"Strategy 4: '{name}' last name '{last_name}' ambiguous "
                f"({len(matches)} matches) — skipping"
            )

    return None, None, None


# ═══════════════════════════════════════════════════════════════
# Cache builders
# ═══════════════════════════════════════════════════════════════

def _build_claim_entity_map(conn, conversation_id: str) -> dict[str, str]:
    """Build name → entity_id map from claim_entities for this conversation.

    Strategy 1 lookup: all entity_names linked to claims in this conversation.
    """
    rows = conn.execute(
        """SELECT DISTINCT ce.entity_name, ce.entity_id
           FROM claim_entities ce
           JOIN event_claims ec ON ec.id = ce.claim_id
           WHERE ec.conversation_id = ?
             AND ce.entity_id IS NOT NULL""",
        (conversation_id,),
    ).fetchall()

    result = {}
    for r in rows:
        name = r["entity_name"]
        if name:
            result[name.strip().lower()] = r["entity_id"]
    return result


def _build_claim_subject_map(conn, conversation_id: str) -> dict[str, str]:
    """Build subject_name → entity_id map from event_claims for this conversation.

    Strategy 2 lookup: claims where subject_entity_id was already resolved.
    """
    rows = conn.execute(
        """SELECT DISTINCT subject_name, subject_entity_id
           FROM event_claims
           WHERE conversation_id = ?
             AND subject_entity_id IS NOT NULL
             AND subject_name IS NOT NULL""",
        (conversation_id,),
    ).fetchall()

    result = {}
    for r in rows:
        name = r["subject_name"]
        if name:
            result[name.strip().lower()] = r["subject_entity_id"]
    return result


def _build_contacts_cache(conn) -> list[dict]:
    """Load all unified_contacts with parsed aliases for Strategy 3+4 lookups."""
    rows = conn.execute(
        "SELECT id, canonical_name, aliases FROM unified_contacts"
    ).fetchall()

    cache = []
    for r in rows:
        aliases_raw = r["aliases"] or ""
        # Aliases are comma-separated or semicolon-separated
        aliases_list = []
        for sep in [",", ";"]:
            if sep in aliases_raw:
                aliases_list = [a.strip() for a in aliases_raw.split(sep) if a.strip()]
                break
        if not aliases_list and aliases_raw.strip():
            aliases_list = [aliases_raw.strip()]

        cache.append({
            "id": r["id"],
            "canonical_name_lower": (r["canonical_name"] or "").strip().lower(),
            "aliases_list": aliases_list,
        })
    return cache


# ═══════════════════════════════════════════════════════════════
# Provisional contact creation
# ═══════════════════════════════════════════════════════════════

def _create_provisional_and_link_claims(
    conn, conversation_id: str, name: str
) -> tuple[str, str, float]:
    """Create a provisional contact for an unresolved name and link matching claims.

    Matches claims by both subject_name AND target_entity.

    Returns (entity_id, resolution_method, confidence).
    """
    import re

    # Skip relational references — these are handled by RelationalReferencesBanner
    RELATIONAL_PATTERNS = [
        re.compile(
            r"^(my|his|her|their|stephen'?s?)\s+(brother|sister|wife|husband|spouse|partner|"
            r"mom|mother|dad|father|son|daughter|boss|assistant|colleague|friend|uncle|aunt|"
            r"cousin|nephew|niece|grandfather|grandmother|grandpa|grandma|fianc[eé]e?|"
            r"roommate|mentor|intern)$",
            re.IGNORECASE,
        ),
        re.compile(r"^(the|a|an)\s+(senator|commissioner|chairman|director|manager|ceo|cfo)$", re.IGNORECASE),
    ]

    for pattern in RELATIONAL_PATTERNS:
        if pattern.match(name.strip()):
            logger.debug(f"Skipping relational reference for provisional: '{name}'")
            return None, None, None

    if len(name.strip()) < 2:
        return None, None, None

    name_lower = name.strip().lower()

    # Check if provisional already exists (from _create_provisional_contacts or a prior run)
    existing = conn.execute(
        """SELECT id FROM unified_contacts
           WHERE LOWER(canonical_name) = ?
              OR LOWER(aliases) LIKE ?""",
        (name_lower, f"%{name_lower}%"),
    ).fetchone()

    if existing:
        entity_id = existing["id"]
        logger.debug(f"Provisional already exists for '{name}': {entity_id[:8]}")
        # Still link claims that reference this name as target_entity
        _link_claims_for_entity(conn, conversation_id, name, entity_id)
        return entity_id, "existing_provisional", 0.40
    else:
        entity_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO unified_contacts
               (id, canonical_name, is_confirmed, source_conversation_id, created_at)
               VALUES (?, ?, 0, ?, datetime('now'))""",
            (entity_id, name.strip(), conversation_id),
        )
        logger.info(f"Created provisional contact: '{name}' (id={entity_id[:8]})")

        # Link matching claims — both subject_name and target_entity
        _link_claims_for_entity(conn, conversation_id, name, entity_id)

        return entity_id, "provisional_created", 0.30


def _link_claims_for_entity(conn, conversation_id: str, name: str, entity_id: str):
    """Link claims that reference this name as subject or target.

    Scans both event_claims.subject_name and event_claims.target_entity.
    """
    name_lower = name.strip().lower()
    linked = 0

    # Link claims where subject_name matches and subject_entity_id is null
    subject_claims = conn.execute(
        """SELECT id FROM event_claims
           WHERE conversation_id = ?
             AND LOWER(subject_name) = ?
             AND subject_entity_id IS NULL""",
        (conversation_id, name_lower),
    ).fetchall()

    for claim in subject_claims:
        try:
            conn.execute(
                "UPDATE event_claims SET subject_entity_id = ? WHERE id = ? AND subject_entity_id IS NULL",
                (entity_id, claim["id"]),
            )
            conn.execute(
                """INSERT OR IGNORE INTO claim_entities
                   (id, claim_id, entity_id, entity_name, role, confidence, link_source)
                   VALUES (?, ?, ?, ?, 'subject', 0.5, 'auto_synthesis')""",
                (str(uuid.uuid4()), claim["id"], entity_id, name.strip()),
            )
            linked += 1
        except Exception:
            pass

    # Link claims where target_entity matches — use claim_entities junction table
    target_claims = conn.execute(
        """SELECT id FROM event_claims
           WHERE conversation_id = ?
             AND LOWER(target_entity) = ?""",
        (conversation_id, name_lower),
    ).fetchall()

    for claim in target_claims:
        # Check if already linked
        existing_link = conn.execute(
            """SELECT id FROM claim_entities
               WHERE claim_id = ? AND entity_id = ? AND role = 'target'""",
            (claim["id"], entity_id),
        ).fetchone()

        if not existing_link:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO claim_entities
                       (id, claim_id, entity_id, entity_name, role, confidence, link_source)
                       VALUES (?, ?, ?, ?, 'target', 0.5, 'auto_synthesis')""",
                    (str(uuid.uuid4()), claim["id"], entity_id, name.strip()),
                )
                linked += 1
            except Exception:
                pass

    if linked:
        logger.debug(f"Linked {linked} claims to entity '{name}' ({entity_id[:8]})")


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _get_canonical_name(conn, entity_id: str) -> str:
    """Look up canonical_name for an entity_id."""
    row = conn.execute(
        "SELECT canonical_name FROM unified_contacts WHERE id = ?",
        (entity_id,),
    ).fetchone()
    return row["canonical_name"] if row else None


# ═══════════════════════════════════════════════════════════════
# Storage
# ═══════════════════════════════════════════════════════════════

def _store_link(
    conn,
    conversation_id: str,
    object_type: str,
    object_index: int,
    field_name: str,
    original_name: str,
    resolved_entity_id: Optional[str],
    resolution_method: Optional[str],
    confidence: Optional[float],
):
    """Insert a synthesis_entity_links row."""
    conn.execute(
        """INSERT OR REPLACE INTO synthesis_entity_links
           (id, conversation_id, object_type, object_index, field_name,
            original_name, resolved_entity_id, resolution_method, confidence, link_source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'auto_synthesis')""",
        (
            str(uuid.uuid4()),
            conversation_id,
            object_type,
            object_index,
            field_name,
            original_name,
            resolved_entity_id,
            resolution_method,
            confidence,
        ),
    )
