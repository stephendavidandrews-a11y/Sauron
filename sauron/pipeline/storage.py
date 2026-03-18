"""DB storage helpers for extraction pipeline results.

Functions:
  store_episodes — store triage episode segments
  store_claims — store atomic claims + entity links
  create_provisional_contacts — create contacts for unrecognized people
  store_belief_updates — upsert beliefs from Opus synthesis
  store_graph_edges — store relationship graph edges
  resolve_graph_entity — resolve entity name to (id, table)
  link_meeting_intentions — auto-link prep intentions to conversations
"""
import json
import logging
import re
import uuid

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


def _store_episodes(conn, conversation_id: str, triage):
    """Store episode segments from Haiku triage."""
    for i, ep in enumerate(triage.episodes):
        ep_id = f"{conversation_id}_ep_{i+1:03d}"
        conn.execute(
            """INSERT OR IGNORE INTO event_episodes
               (id, conversation_id, title, episode_type, start_time, end_time, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ep_id, conversation_id, ep.title, ep.episode_type,
             ep.start_time, ep.end_time, ep.summary),
        )



def _store_claims(conn, conversation_id: str, claims_result):
    """Store atomic claims from Sonnet extraction."""
    for claim in claims_result.claims:
        claim_id = f"{conversation_id}_{claim.id}"
        episode_id = None
        if claim.episode_id:
            try:
                ep_num = int(claim.episode_id.split("_")[-1])
                episode_id = f"{conversation_id}_ep_{ep_num:03d}"
            except (ValueError, IndexError):
                episode_id = None

        conn.execute(
            """INSERT OR IGNORE INTO event_claims
               (id, conversation_id, episode_id, claim_type, claim_text,
                subject_entity_id, subject_name, subject_type, target_entity, speaker_id,
                modality, polarity, confidence, stability,
                evidence_quote, evidence_start, evidence_end, review_after,
                importance, evidence_type,
                firmness, has_specific_action, has_deadline, has_condition,
                condition_text, direction, time_horizon)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?)""",
            (claim_id, conversation_id, episode_id,
             claim.claim_type, claim.claim_text,
             claim.subject_entity_id, claim.subject_name,
             getattr(claim, 'subject_type', 'person'), claim.target_entity,
             claim.speaker, claim.modality, claim.polarity,
             claim.confidence, claim.stability,
             claim.evidence_quote, claim.evidence_start, claim.evidence_end,
             claim.review_after, claim.importance, claim.evidence_type,
             getattr(claim, 'firmness', None),
             getattr(claim, 'has_specific_action', None),
             getattr(claim, 'has_deadline', None),
             getattr(claim, 'has_condition', None),
             getattr(claim, 'condition_text', None),
             getattr(claim, 'direction', None),
             getattr(claim, 'time_horizon', None)),
        )

        # B3: Store additional entity links from multi-entity claims
        additional = getattr(claim, 'additional_entities', None)
        if additional:
            for ae in additional:
                ae_name = (ae.get("name") or "").strip()
                ae_role = ae.get("role", "target")
                if not ae_name:
                    continue
                # Quick lookup against unified_contacts
                contact = conn.execute(
                    "SELECT id, canonical_name FROM unified_contacts "
                    "WHERE LOWER(TRIM(canonical_name)) = ?",
                    (ae_name.lower(),)
                ).fetchone()
                if not contact:
                    contact = conn.execute(
                        "SELECT id, canonical_name FROM unified_contacts "
                        "WHERE LOWER(aliases) LIKE ?",
                        (f"%{ae_name.lower()}%",)
                    ).fetchone()
                if contact:
                    conn.execute(
                        """INSERT OR IGNORE INTO claim_entities
                           (id, claim_id, entity_id, entity_name, role, confidence,
                            link_source, entity_table)
                           VALUES (?, ?, ?, ?, ?, ?, 'model', 'unified_contacts')""",
                        (str(uuid.uuid4()), claim_id, dict(contact)["id"],
                         dict(contact)["canonical_name"], ae_role, claim.confidence),
                    )
                else:
                    logger.debug(
                        f"Additional entity '{ae_name}' not found in contacts — "
                        f"deferred to entity resolver"
                    )


def _create_provisional_contacts(conn, conversation_id: str, claims_result):
    """Create provisional unified_contacts for unrecognized people mentioned in claims."""
    if not claims_result.new_contacts_mentioned:
        return

    import re as _re

    RELATIONAL_PATTERNS = [
        _re.compile(r"^(my|his|her|their|stephen'?s?)\s+(brother|sister|wife|husband|spouse|partner|"
                    r"mom|mother|dad|father|son|daughter|boss|assistant|colleague|friend|uncle|aunt|"
                    r"cousin|nephew|niece|grandfather|grandmother|grandpa|grandma|fianc[ee]e?|"
                    r"roommate|mentor|intern)$", _re.IGNORECASE),
        _re.compile(r"^(a|the|some)\s+\w+$", _re.IGNORECASE),
    ]

    created = 0
    linked = 0

    for mention in claims_result.new_contacts_mentioned:
        # Handle both string and structured NewContactMention
        if isinstance(mention, str):
            name = mention.strip()
        else:
            # Structured NewContactMention object
            name = (getattr(mention, 'name', '') or '').strip()
        if not name:
            continue

        is_relational = False
        for pattern in RELATIONAL_PATTERNS:
            if pattern.match(name):
                is_relational = True
                break
        if is_relational:
            logger.debug(f"Skipping relational reference: '{name}'")
            continue

        if len(name) < 2:
            continue

        name_lower = name.lower().strip()
        existing = conn.execute(
            """SELECT id, canonical_name FROM unified_contacts
               WHERE LOWER(canonical_name) = ?
                  OR LOWER(aliases) LIKE ?""",
            (name_lower, f"%{name_lower}%"),
        ).fetchone()

        if existing:
            logger.debug(f"Contact already exists for '{name}': {existing['canonical_name']}")
            continue

        contact_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO unified_contacts
               (id, canonical_name, is_confirmed, source_conversation_id, created_at)
               VALUES (?, ?, 0, ?, datetime('now'))""",
            (contact_id, name, conversation_id),
        )
        created += 1
        logger.info(f"Created provisional contact: '{name}' (id={contact_id[:8]})")

        matching_claims = conn.execute(
            """SELECT id, subject_name FROM event_claims
               WHERE conversation_id = ?
                 AND LOWER(subject_name) = ?
                 AND subject_entity_id IS NULL""",
            (conversation_id, name_lower),
        ).fetchall()

        for claim in matching_claims:
            claim_dict = dict(claim)
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO claim_entities
                       (id, claim_id, entity_id, entity_name, role, confidence, link_source)
                       VALUES (?, ?, ?, ?, 'subject', 0.5, 'model')""",
                    (str(uuid.uuid4()), claim_dict["id"], contact_id, name),
                )
                conn.execute(
                    "UPDATE event_claims SET subject_entity_id = ? WHERE id = ? AND subject_entity_id IS NULL",
                    (contact_id, claim_dict["id"]),
                )
                linked += 1
            except Exception:
                pass

    if created:
        logger.info(
            f"Provisional contacts for {conversation_id[:8]}: "
            f"{created} created, {linked} claim links"
        )



def _store_belief_updates(conn, conversation_id, synthesis, claims_result):
    """Store belief updates and evidence links from Opus synthesis."""
    now = datetime.now(timezone.utc).isoformat()

    for bu in synthesis.belief_updates:
        belief_id = str(uuid.uuid4())

        existing = conn.execute(
            "SELECT id, support_count, contradiction_count FROM beliefs WHERE belief_key = ? AND entity_id = ?",
            (bu.belief_key, bu.entity_id),
        ).fetchone()

        if existing:
            if bu.evidence_role == "support":
                _old_status = conn.execute(
                    "SELECT status FROM beliefs WHERE id = ?", (existing["id"],)
                ).fetchone()["status"]
                conn.execute(
                    """UPDATE beliefs SET
                       belief_summary = ?, status = ?, confidence = ?,
                       support_count = support_count + 1,
                       last_confirmed_at = ?, last_changed_at = ?
                       WHERE id = ?""",
                    (bu.belief_summary, bu.status, bu.confidence, now, now, existing["id"]),
                )
                belief_id = existing["id"]
                if _old_status != bu.status:
                    conn.execute(
                        """INSERT INTO belief_transitions
                           (id, belief_id, old_status, new_status, driver, source_conversation_id)
                           VALUES (?, ?, ?, ?, 'new_evidence', ?)""",
                        (str(uuid.uuid4()), existing["id"], _old_status, bu.status, conversation_id),
                    )
            elif bu.evidence_role == "contradiction":
                _old_status = conn.execute(
                    "SELECT status FROM beliefs WHERE id = ?", (existing["id"],)
                ).fetchone()["status"]
                conn.execute(
                    """UPDATE beliefs SET
                       status = 'contested', contradiction_count = contradiction_count + 1,
                       last_changed_at = ?
                       WHERE id = ?""",
                    (now, existing["id"]),
                )
                belief_id = existing["id"]
                if _old_status != 'contested':
                    conn.execute(
                        """INSERT INTO belief_transitions
                           (id, belief_id, old_status, new_status, driver, source_conversation_id)
                           VALUES (?, ?, ?, 'contested', 'new_evidence', ?)""",
                        (str(uuid.uuid4()), existing["id"], _old_status, conversation_id),
                    )
            elif bu.evidence_role in ("refinement", "qualification"):
                _old_status = conn.execute(
                    "SELECT status FROM beliefs WHERE id = ?", (existing["id"],)
                ).fetchone()["status"]
                conn.execute(
                    """UPDATE beliefs SET
                       belief_summary = ?, status = ?, confidence = ?,
                       last_changed_at = ?
                       WHERE id = ?""",
                    (bu.belief_summary, bu.status, bu.confidence, now, existing["id"]),
                )
                belief_id = existing["id"]
                if _old_status != bu.status:
                    conn.execute(
                        """INSERT INTO belief_transitions
                           (id, belief_id, old_status, new_status, driver, source_conversation_id)
                           VALUES (?, ?, ?, ?, 'new_evidence', ?)""",
                        (str(uuid.uuid4()), existing["id"], _old_status, bu.status, conversation_id),
                    )
        else:
            conn.execute(
                """INSERT INTO beliefs
                   (id, entity_type, entity_id, belief_key, belief_summary,
                    status, confidence, support_count, contradiction_count,
                    first_observed_at, last_confirmed_at, last_changed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (belief_id, bu.entity_type, bu.entity_id, bu.belief_key,
                 bu.belief_summary, bu.status, bu.confidence,
                 1 if bu.evidence_role == "support" else 0,
                 1 if bu.evidence_role == "contradiction" else 0,
                 now, now, now),
            )
            conn.execute(
                """INSERT INTO belief_transitions
                   (id, belief_id, old_status, new_status, driver, source_conversation_id)
                   VALUES (?, ?, NULL, ?, 'new_evidence', ?)""",
                (str(uuid.uuid4()), belief_id, bu.status, conversation_id),
            )

        for claim_ref in bu.supporting_claim_ids:
            claim_db_id = f"{conversation_id}_{claim_ref}"
            conn.execute(
                """INSERT OR IGNORE INTO belief_evidence
                   (id, belief_id, claim_id, weight, evidence_role)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), belief_id, claim_db_id,
                 bu.confidence, bu.evidence_role),
            )

        # C8: Resolve entity_id for beliefs
        if bu.entity_type and bu.entity_type != 'person' and bu.entity_name and not bu.entity_id:
            entity_row = conn.execute(
                "SELECT id FROM unified_entities WHERE LOWER(canonical_name) = ?",
                (bu.entity_name.strip().lower(),),
            ).fetchone()
            if entity_row:
                conn.execute(
                    "UPDATE beliefs SET entity_id = ? WHERE id = ?",
                    (entity_row["id"], belief_id),
                )
        elif bu.entity_type == 'person' and bu.entity_name and not bu.entity_id:
            contact_row = conn.execute(
                "SELECT id FROM unified_contacts WHERE LOWER(canonical_name) = ?",
                (bu.entity_name.strip().lower(),),
            ).fetchone()
            if contact_row:
                conn.execute(
                    "UPDATE beliefs SET entity_id = ? WHERE id = ?",
                    (contact_row["id"], belief_id),
                )



def _resolve_graph_entity(conn, name: str, entity_type: str):
    """Resolve graph edge entity name to (id, table) tuple."""
    if not name:
        return None, None
    name_lower = name.strip().lower()
    if entity_type == "person":
        row = conn.execute(
            "SELECT id FROM unified_contacts WHERE LOWER(canonical_name) = ?",
            (name_lower,),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id FROM unified_contacts WHERE LOWER(aliases) LIKE ?",
                (f"%{name_lower}%",),
            ).fetchone()
        return (row["id"], "unified_contacts") if row else (None, None)
    else:
        row = conn.execute(
            "SELECT id FROM unified_entities WHERE LOWER(canonical_name) = ?",
            (name_lower,),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id FROM unified_entities WHERE LOWER(aliases) LIKE ?",
                (f"%{name_lower}%",),
            ).fetchone()
        return (row["id"], "unified_entities") if row else (None, None)


def _store_graph_edges(conn, conversation_id, synthesis):
    """Store graph edges from Opus synthesis.

    Clears any existing edges for this conversation first to prevent
    accumulation across reprocessing runs.
    """
    deleted = conn.execute(
        "DELETE FROM graph_edges WHERE source_conversation_id = ?",
        (conversation_id,),
    ).rowcount
    if deleted:
        logger.info(f"[{conversation_id[:8]}] Cleared {deleted} old graph edges before storing new ones")

    now = datetime.now(timezone.utc).isoformat()
    for edge in synthesis.graph_edges:
        edge_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO graph_edges
               (id, from_entity, from_type, to_entity, to_type,
                edge_type, strength, source_conversation_id, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (edge_id, edge.from_entity, edge.from_type,
             edge.to_entity, edge.to_type, edge.edge_type,
             edge.strength, conversation_id, now),
        )

        # Resolve entity IDs for this edge
        from_id, from_table = _resolve_graph_entity(conn, edge.from_entity, edge.from_type)
        to_id, to_table = _resolve_graph_entity(conn, edge.to_entity, edge.to_type)
        if from_id or to_id:
            conn.execute(
                """UPDATE graph_edges
                   SET from_entity_id=?, from_entity_table=?,
                       to_entity_id=?, to_entity_table=?
                   WHERE id=?""",
                (from_id, from_table, to_id, to_table, edge_id),
            )



def _link_meeting_intentions(conn, conversation_id, speaker_map, extraction_result):
    """Auto-link meeting intentions when target contact participates."""
    try:
        from sauron.jobs.intentions import (
            find_unlinked_intention,
            link_intention_to_conversation,
            assess_goals,
        )
        for label, contact_id in speaker_map.items():
            if contact_id:
                intention_id = find_unlinked_intention(contact_id)
                if intention_id:
                    link_intention_to_conversation(intention_id, conversation_id)
                    if extraction_result:
                        assess_goals(intention_id, extraction_result)
                    break
    except Exception:
        logger.exception("Intention linking failed (non-fatal)")

