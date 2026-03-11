"""7-step entity confirmation cascade.

When a person→contact mapping is confirmed (via review UI, graph.py provisional
management, or auto-synthesis confirmation), this cascade propagates the
confirmation to all downstream records.

Called from:
  - graph.py: link_provisional_to_existing, confirm_provisional_contact
  - conversations.py: confirm-person endpoint

See: docs/specs/entity_resolution_review_plan.md, Phase 3.
"""

import logging

logger = logging.getLogger(__name__)


def cascade_entity_confirmation(
    conn,
    entity_id: str,
    canonical_name: str,
    original_names: list[str],
    conversation_id: str | None = None,
    source: str = "cascade",
) -> dict:
    """Execute 7-step cascade after confirming a person→contact mapping.

    Args:
        conn: SQLite connection (caller manages transaction).
        entity_id: The unified_contacts.id of the confirmed contact.
        canonical_name: The contact's canonical_name.
        original_names: Names that should resolve to this entity
                        (e.g., the provisional name, aliases, extracted names).
        conversation_id: Scope to one conversation, or None for all.
        source: link_source tag for correction_events / claim_entities.

    Returns:
        Stats dict with counts per step.
    """
    stats = {
        "step1_subject_linked": 0,
        "step2_target_linked": 0,
        "step3_text_rewritten": 0,
        "step4_titles_updated": 0,
        "step5_synthesis_links": 0,
        "step6_relational_refs": [],
        "step7_aliases_learned": 0,
    }

    if not original_names or not entity_id or not canonical_name:
        return stats

    # Normalize: strip whitespace, remove empties
    clean_names = [n.strip() for n in original_names if n and n.strip()]
    if not clean_names:
        return stats

    names_lower = list({n.lower() for n in clean_names})
    affected_claim_ids = set()

    # ── Step 1: Subject linking ──────────────────────────────────
    # Find claims where subject_name matches but isn't yet linked to entity_id
    try:
        from sauron.api.corrections import sync_claim_entities_subject

        placeholders = ",".join("?" for _ in names_lower)
        conv_clause = "AND ec.conversation_id = ?" if conversation_id else ""
        conv_params = [conversation_id] if conversation_id else []

        query = f"""
            SELECT ec.id, ec.subject_name, ec.subject_entity_id, ec.review_status
            FROM event_claims ec
            WHERE LOWER(TRIM(ec.subject_name)) IN ({placeholders})
              AND (ec.subject_entity_id IS NULL OR ec.subject_entity_id != ?)
              AND (ec.review_status IS NULL
                   OR ec.review_status NOT IN ('user_confirmed', 'user_corrected', 'dismissed'))
              {conv_clause}
        """
        params = names_lower + [entity_id] + conv_params
        rows = conn.execute(query, params).fetchall()

        for row in rows:
            try:
                sync_claim_entities_subject(
                    conn, row["id"], entity_id, canonical_name, source
                )
                stats["step1_subject_linked"] += 1
                affected_claim_ids.add(row["id"])
            except Exception:
                logger.exception(
                    f"Cascade Step 1 failed for claim {row['id'][:8]}"
                )
    except Exception:
        logger.exception("Cascade Step 1 import/query failed")

    # ── Step 2: Target linking ───────────────────────────────────
    # Find claim_entities with role='target' that match original names
    try:
        placeholders = ",".join("?" for _ in names_lower)
        conv_clause = "AND ec.conversation_id = ?" if conversation_id else ""
        conv_params = [conversation_id] if conversation_id else []

        query = f"""
            SELECT ce.id, ce.claim_id, ce.entity_name
            FROM claim_entities ce
            JOIN event_claims ec ON ec.id = ce.claim_id
            WHERE ce.role = 'target'
              AND LOWER(TRIM(ce.entity_name)) IN ({placeholders})
              AND (ce.entity_id IS NULL OR ce.entity_id != ?)
              {conv_clause}
        """
        params = names_lower + [entity_id] + conv_params
        rows = conn.execute(query, params).fetchall()

        for row in rows:
            try:
                conn.execute(
                    """UPDATE claim_entities
                       SET entity_id = ?, entity_name = ?, link_source = ?
                       WHERE id = ?""",
                    (entity_id, canonical_name, source, row["id"]),
                )
                stats["step2_target_linked"] += 1
                affected_claim_ids.add(row["claim_id"])
            except Exception:
                logger.exception(
                    f"Cascade Step 2 failed for claim_entity {row['id'][:8]}"
                )
    except Exception:
        logger.exception("Cascade Step 2 query failed")

    # ── Step 3: Text rewriting ───────────────────────────────────
    # Replace original names with canonical name in claim_text
    if affected_claim_ids:
        try:
            from sauron.api.entity_helpers import replace_name_in_text

            placeholders = ",".join("?" for _ in affected_claim_ids)
            claims = conn.execute(
                f"""SELECT id, claim_text, text_user_edited
                    FROM event_claims WHERE id IN ({placeholders})""",
                list(affected_claim_ids),
            ).fetchall()

            for claim in claims:
                if claim["text_user_edited"]:
                    continue  # respect user edits
                text = claim["claim_text"]
                if not text:
                    continue

                new_text = text
                for orig_name in clean_names:
                    result = replace_name_in_text(new_text, orig_name, canonical_name)
                    if result and result != new_text:
                        new_text = result

                if new_text != text:
                    conn.execute(
                        "UPDATE event_claims SET claim_text = ? WHERE id = ?",
                        (new_text, claim["id"]),
                    )
                    stats["step3_text_rewritten"] += 1
        except Exception:
            logger.exception("Cascade Step 3 failed")

    # ── Step 4: Episode titles ───────────────────────────────────
    # Replace original names with canonical name in episode titles
    try:
        conv_clause = "AND conversation_id = ?" if conversation_id else ""
        conv_params = [conversation_id] if conversation_id else []

        for orig_name in clean_names:
            episodes = conn.execute(
                f"""SELECT id, title FROM event_episodes
                    WHERE title LIKE ? {conv_clause}""",
                [f"%{orig_name}%"] + conv_params,
            ).fetchall()

            for ep in episodes:
                new_title = ep["title"].replace(orig_name, canonical_name)
                if new_title != ep["title"]:
                    conn.execute(
                        "UPDATE event_episodes SET title = ? WHERE id = ?",
                        (new_title, ep["id"]),
                    )
                    stats["step4_titles_updated"] += 1
    except Exception:
        logger.exception("Cascade Step 4 failed")

    # ── Step 5: synthesis_entity_links ───────────────────────────
    # Update resolution records to confirmed
    try:
        conv_clause = "AND conversation_id = ?" if conversation_id else ""
        conv_params = [conversation_id] if conversation_id else []

        for orig_name in clean_names:
            updated = conn.execute(
                f"""UPDATE synthesis_entity_links
                    SET resolved_entity_id = ?, resolution_method = 'cascade',
                        confidence = 0.95, link_source = ?
                    WHERE LOWER(TRIM(original_name)) = LOWER(?)
                      AND (resolved_entity_id IS NULL OR resolved_entity_id != ?)
                      {conv_clause}""",
                [entity_id, source, orig_name, entity_id] + conv_params,
            ).rowcount
            stats["step5_synthesis_links"] += updated
    except Exception:
        logger.exception("Cascade Step 5 failed")

    # ── Step 6: Relational reference detection ───────────────────
    # Scan claims for relational references anchored on canonical_name
    # (e.g., confirming "Stephen Weber" enables "Stephen Weber's son")
    try:
        from sauron.api.corrections import _detect_relational_reference

        conv_clause = "AND conversation_id = ?" if conversation_id else ""
        conv_params = [conversation_id] if conversation_id else []

        claims = conn.execute(
            f"""SELECT id, claim_text FROM event_claims
                WHERE claim_text IS NOT NULL
                  {conv_clause}""",
            conv_params,
        ).fetchall()

        for claim in claims:
            ref = _detect_relational_reference(
                claim["claim_text"], [canonical_name]
            )
            if ref:
                stats["step6_relational_refs"].append(
                    {"claim_id": claim["id"], **ref}
                )
    except Exception:
        logger.exception("Cascade Step 6 failed")

    # ── Step 7: Alias learning ───────────────────────────────────
    try:
        from sauron.extraction.alias_learner import learn_alias

        for name in clean_names:
            if learn_alias(conn, entity_id, name, canonical_name):
                stats["step7_aliases_learned"] += 1
    except Exception:
        logger.exception("Cascade Step 7 failed")

    logger.info(
        f"Cascade for '{canonical_name}': "
        f"S1={stats['step1_subject_linked']} S2={stats['step2_target_linked']} "
        f"S3={stats['step3_text_rewritten']} S4={stats['step4_titles_updated']} "
        f"S5={stats['step5_synthesis_links']} S6={len(stats['step6_relational_refs'])} "
        f"S7={stats['step7_aliases_learned']}"
    )

    return stats
