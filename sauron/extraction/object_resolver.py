"""Resolve non-person claim subjects against unified_entities.

Mirrors entity_resolver.py pattern but for organizations, legislation, topics.
Called after claims storage when subject_type != 'person'.

Resolution stages:
  1. Direct canonical_name match (case-insensitive)
  2. Alias match (semicolon-separated, case-insensitive)
  3. If no match: create provisional unified_entities row

No relational term matching (not relevant for orgs/legislation).
No conversation connection verification (not needed for objects).
Same user correction protection as entity_resolver.
"""

import json
import logging
import uuid

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

# Subtype table mapping
_SUBTYPE_TABLE = {
    "organization": "entity_organizations",
    "legislation": "entity_legislation",
    "topic": "entity_topics",
}


def resolve_object_entities(conversation_id: str) -> dict:
    """Match non-person subject_names to unified_entities.

    Returns dict: {resolved, created, skipped, errors}
    """
    conn = get_connection()
    stats = {"resolved": 0, "created": 0, "skipped": 0, "errors": 0}

    try:
        # 1. Load claims where subject_type != 'person' AND unlinked
        claims = conn.execute(
            """SELECT id, subject_name, subject_type, review_status
               FROM event_claims
               WHERE conversation_id = ?
                 AND subject_type IS NOT NULL
                 AND subject_type != 'person'
                 AND subject_entity_id IS NULL
                 AND subject_name IS NOT NULL AND subject_name != ''
                 AND (review_status IS NULL
                      OR review_status NOT IN ('user_corrected', 'user_confirmed'))""",
            (conversation_id,),
        ).fetchall()

        if not claims:
            return stats

        # 2. Check for user-protected claim_entities
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

        # 3. Build lookup structures from unified_entities
        entities = conn.execute(
            "SELECT id, entity_type, canonical_name, aliases FROM unified_entities"
        ).fetchall()

        name_to_entity = {}   # lowercase canonical -> entity dict
        alias_to_entity = {}  # lowercase alias -> entity dict

        for e in entities:
            ed = dict(e)
            name_key = ed["canonical_name"].lower().strip()
            name_to_entity.setdefault(name_key, []).append(ed)

            aliases = ed.get("aliases") or ""
            for alias in aliases.split(";"):
                alias = alias.strip().lower()
                if alias:
                    alias_to_entity.setdefault(alias, []).append(ed)

        # 4. Resolve each claim
        for claim in claims:
            cd = dict(claim)
            claim_id = cd["id"]
            subject = cd["subject_name"].strip()
            subject_type = cd["subject_type"]
            subject_lower = subject.lower()

            if claim_id in user_linked_claims:
                stats["skipped"] += 1
                continue

            match = None

            # Stage 1: Direct canonical name match
            candidates = name_to_entity.get(subject_lower, [])
            if len(candidates) == 1:
                match = candidates[0]
            elif len(candidates) > 1:
                # Prefer matching entity_type
                typed = [c for c in candidates if c["entity_type"] == subject_type]
                if len(typed) == 1:
                    match = typed[0]

            # Stage 2: Alias match
            if not match:
                candidates = alias_to_entity.get(subject_lower, [])
                if len(candidates) == 1:
                    match = candidates[0]
                elif len(candidates) > 1:
                    typed = [c for c in candidates if c["entity_type"] == subject_type]
                    if len(typed) == 1:
                        match = typed[0]

            if match:
                # Update event_claims
                conn.execute(
                    "UPDATE event_claims SET subject_entity_id = ? WHERE id = ?",
                    (match["id"], claim_id),
                )

                # Write claim_entities junction
                conn.execute(
                    """INSERT OR IGNORE INTO claim_entities
                       (id, claim_id, entity_id, entity_name, role, confidence,
                        link_source, entity_table)
                       VALUES (?, ?, ?, ?, 'subject', NULL, 'resolver', 'unified_entities')""",
                    (str(uuid.uuid4()), claim_id, match["id"],
                     match["canonical_name"]),
                )

                # Increment observation_count, update last_observed_at
                conn.execute(
                    """UPDATE unified_entities
                       SET observation_count = observation_count + 1,
                           last_observed_at = datetime('now')
                       WHERE id = ?""",
                    (match["id"],),
                )

                # Learn alias if name differs
                try:
                    from sauron.extraction.alias_learner import learn_entity_alias
                    learn_entity_alias(conn, match["id"], subject, match["canonical_name"])
                except Exception:
                    pass

                stats["resolved"] += 1
                logger.debug(
                    f"Object resolved '{subject}' -> {match['canonical_name']} "
                    f"for claim {claim_id[:8]}"
                )

            else:
                # Create provisional entity
                try:
                    entity_id = str(uuid.uuid4())
                    conn.execute(
                        """INSERT INTO unified_entities
                           (id, entity_type, canonical_name, is_confirmed,
                            source_conversation_id, first_observed_at,
                            last_observed_at, observation_count)
                           VALUES (?, ?, ?, 0, ?, datetime('now'), datetime('now'), 1)""",
                        (entity_id, subject_type, subject, conversation_id),
                    )

                    # Create sparse subtype row
                    subtype_table = _SUBTYPE_TABLE.get(subject_type)
                    if subtype_table:
                        conn.execute(
                            f"INSERT OR IGNORE INTO {subtype_table} (entity_id) VALUES (?)",
                            (entity_id,),
                        )

                    # Update event_claims
                    conn.execute(
                        "UPDATE event_claims SET subject_entity_id = ? WHERE id = ?",
                        (entity_id, claim_id),
                    )

                    # Write claim_entities junction
                    conn.execute(
                        """INSERT OR IGNORE INTO claim_entities
                           (id, claim_id, entity_id, entity_name, role, confidence,
                            link_source, entity_table)
                           VALUES (?, ?, ?, ?, 'subject', NULL, 'resolver', 'unified_entities')""",
                        (str(uuid.uuid4()), claim_id, entity_id, subject),
                    )

                    # Update lookup caches for subsequent claims in same batch
                    ed = {"id": entity_id, "entity_type": subject_type,
                          "canonical_name": subject, "aliases": ""}
                    name_to_entity.setdefault(subject_lower, []).append(ed)

                    stats["created"] += 1
                    logger.info(
                        f"Created provisional entity: '{subject}' "
                        f"(type={subject_type}, id={entity_id[:8]})"
                    )
                except Exception:
                    stats["errors"] += 1
                    logger.exception(f"Failed to create provisional entity for '{subject}'")

        conn.commit()
        logger.info(
            f"Object resolution for {conversation_id[:8]}: "
            f"{stats['resolved']} resolved, {stats['created']} created, "
            f"{stats['skipped']} skipped, {stats['errors']} errors"
        )
    except Exception:
        conn.rollback()
        logger.exception("Object resolution failed")
        raise
    finally:
        conn.close()

    return stats
