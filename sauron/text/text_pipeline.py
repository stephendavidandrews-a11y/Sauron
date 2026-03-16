"""Text pipeline integration — wires text extraction into the review system.

Takes extracted claims from text_extraction.py and:
1. Creates a conversations record (modality='text')
2. Links text_clusters.conversation_id
3. Stores claims in event_claims
4. Assigns review tiers via review_policy
5. Runs condition checker for conditional commitments
6. Sets processing_status for review queue

This module bridges the text extraction world (text_clusters, text_messages)
with the shared review world (conversations, event_claims, review_actions).
"""

import json
import logging
import sqlite3

from sauron.db.connection import get_connection as _db_conn
import uuid
from datetime import datetime, timezone

from sauron.config import DB_PATH
from sauron.extraction.schemas import ClaimsResult
from sauron.text.review_policy import assign_review_tier

logger = logging.getLogger(__name__)


def _get_conn(db_path=None) -> sqlite3.Connection:
    """Get a connection with WAL, FK, and busy_timeout pragmas."""
    if db_path is None:
        return _db_conn()
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add new columns to event_claims if they don't exist yet."""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(event_claims)").fetchall()
    }
    new_columns = {
        "due_date": "TEXT",
        "date_confidence": "TEXT",
        "date_note": "TEXT",
        "condition_trigger": "TEXT",
        "recurrence": "TEXT",
        "related_claim_id": "TEXT",
        "review_tier": "TEXT",
    }
    for col, col_type in new_columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE event_claims ADD COLUMN {col} {col_type}")
            logger.info("Added column event_claims.%s", col)
    conn.commit()


def process_text_cluster(
    cluster_id: str,
    triage: dict,
    claims_result: ClaimsResult | None,
    metadata: dict,
    db_path=None,
) -> dict:
    """Process an extracted text cluster into the review pipeline.

    Args:
        cluster_id: text_clusters.id
        triage: Triage result dict (from triage_text_cluster)
        claims_result: ClaimsResult from extract_text_claims (None for Lane 0/1)
        metadata: Cluster metadata dict

    Returns:
        dict with conversation_id, claim_count, tier_distribution, processing_status
    """
    conn = _get_conn(db_path)
    try:
        _ensure_columns(conn)

        depth_lane = triage.get("depth_lane", 0)
        cluster_summary = triage.get("summary", "")
        title = _build_title(metadata, triage)

        # 1. Create conversations record
        conversation_id = f"text_{cluster_id}"

        captured_at = metadata.get("start_time", datetime.now(timezone.utc).isoformat())

        # Determine processing_status based on depth lane and claims
        if depth_lane <= 1 or claims_result is None or not claims_result.claims:
            # Lane 0/1: no claims to review. Mark as completed (triage-only).
            processing_status = "completed"
        else:
            processing_status = "awaiting_claim_review"

        conn.execute("""
            INSERT OR REPLACE INTO conversations
                (id, source, captured_at, context_classification,
                 processing_status, processed_at, title, modality,
                 current_stage, stage_detail, run_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            conversation_id,
            "text_cluster",
            captured_at,
            triage.get("context_classification", "mixed"),
            processing_status,
            datetime.now(timezone.utc).isoformat(),
            title,
            "text",
            "human_review" if processing_status == "awaiting_claim_review" else "completed",
            json.dumps({"depth_lane": depth_lane, "cluster_id": cluster_id}),
            "awaiting_review" if processing_status == "awaiting_claim_review" else "completed",
        ))

        # 2. Link text_clusters.conversation_id
        conn.execute(
            "UPDATE text_clusters SET conversation_id = ?, depth_lane = ? WHERE id = ?",
            (conversation_id, depth_lane, cluster_id),
        )

        # 3. Store triage in extractions table (same pattern as voice)
        triage_json = json.dumps(triage, default=str)
        conn.execute("""
            INSERT OR REPLACE INTO extractions
                (id, conversation_id, pass_number, model_used, extraction_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            f"{conversation_id}_triage",
            conversation_id,
            1,  # pass 1 = triage
            "haiku",
            triage_json,
            datetime.now(timezone.utc).isoformat(),
        ))

        # 4. Store claims in event_claims
        claim_count = 0
        tier_dist = {"auto_route": 0, "quick_review": 0, "hold": 0}

        if claims_result and claims_result.claims:
            claims_json = claims_result.model_dump_json()
            conn.execute("""
                INSERT OR REPLACE INTO extractions
                    (id, conversation_id, pass_number, model_used, extraction_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                f"{conversation_id}_claims",
                conversation_id,
                2,  # pass 2 = claims
                "sonnet",
                claims_json,
                datetime.now(timezone.utc).isoformat(),
            ))

            for claim in claims_result.claims:
                claim_id = f"{conversation_id}_{claim.id}"
                tier = assign_review_tier(claim, modality="text")
                tier_dist[tier] += 1

                conn.execute("""
                    INSERT OR IGNORE INTO event_claims
                        (id, conversation_id, claim_type, claim_text,
                         subject_entity_id, subject_name, subject_type, target_entity,
                         speaker_id, modality, polarity, confidence, stability,
                         evidence_quote, evidence_start, evidence_end,
                         review_after, importance, evidence_type,
                         firmness, has_specific_action, has_deadline,
                         has_condition, condition_text, direction, time_horizon,
                         evidence_quality, review_tier,
                         due_date, date_confidence, date_note,
                         condition_trigger, recurrence, related_claim_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    claim_id,
                    conversation_id,
                    claim.claim_type,
                    claim.claim_text,
                    claim.subject_entity_id,
                    claim.subject_name,
                    getattr(claim, 'subject_type', 'person'),
                    claim.target_entity,
                    claim.speaker,
                    claim.modality,
                    claim.polarity,
                    claim.confidence,
                    claim.stability,
                    claim.evidence_quote,
                    claim.evidence_start,
                    claim.evidence_end,
                    claim.review_after,
                    claim.importance,
                    claim.evidence_type,
                    claim.firmness,
                    claim.has_specific_action,
                    claim.has_deadline,
                    claim.has_condition,
                    claim.condition_text,
                    claim.direction,
                    claim.time_horizon,
                    getattr(claim, "evidence_quality", None),
                    tier,
                    getattr(claim, "due_date", None),
                    getattr(claim, "date_confidence", None),
                    getattr(claim, "date_note", None),
                    getattr(claim, "condition_trigger", None),
                    getattr(claim, "recurrence", None),
                    _resolve_related_claim_id(
                        conversation_id,
                        getattr(claim, "related_claim_id", None),
                    ),
                ))

                # B3: Store additional entity links from multi-entity claims
                additional = getattr(claim, 'additional_entities', None)
                if additional:
                    for ae in additional:
                        ae_name = (ae.get("name") or "").strip()
                        ae_role = ae.get("role", "target")
                        if not ae_name:
                            continue
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
                                   (id, claim_id, entity_id, entity_name, role,
                                    confidence, link_source, entity_table)
                                   VALUES (?, ?, ?, ?, ?, ?, 'model', 'unified_contacts')""",
                                (str(uuid.uuid4()), claim_id, dict(contact)["id"],
                                 dict(contact)["canonical_name"], ae_role,
                                 claim.confidence),
                            )

                claim_count += 1

            # 5. Store new contacts mentioned
            _store_new_contacts(conn, conversation_id, claims_result)

            # 5b. Create provisional contacts for all people_mentioned
            _create_provisional_from_people_mentioned(
                conn, conversation_id, claims_result,
            )

            # 6. Store memory writes as metadata
            if claims_result.memory_writes:
                mw_json = json.dumps(
                    [mw.model_dump() for mw in claims_result.memory_writes],
                    default=str,
                )
                conn.execute("""
                    INSERT OR REPLACE INTO extractions
                        (id, conversation_id, pass_number, model_used,
                         extraction_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    f"{conversation_id}_memory_writes",
                    conversation_id,
                    4,  # pass 4 = memory writes
                    "sonnet",
                    mw_json,
                    datetime.now(timezone.utc).isoformat(),
                ))

        conn.commit()

        # 6b. Entity resolution — match subject_name to unified_contacts
        try:
            from sauron.extraction.entity_resolver import resolve_claim_entities
            entity_stats = resolve_claim_entities(conversation_id)

            # Resolve non-person entities (orgs, legislation, topics)
            try:
                from sauron.extraction.object_resolver import resolve_object_entities
                obj_stats = resolve_object_entities(conversation_id)
                if obj_stats.get("resolved") or obj_stats.get("created"):
                    logger.info(
                        "[TextPipeline] Object resolution for %s: %s",
                        conversation_id[:8], obj_stats,
                    )
            except Exception:
                logger.exception("Object resolution failed (non-fatal)")
            logger.info(
                "[TextPipeline] Entity resolution for %s: %s",
                conversation_id[:8], entity_stats,
            )
        except Exception:
            logger.exception("Entity resolution failed (non-fatal)")

        # 7. Run condition checker (post-extraction enrichment)
        condition_matches = []
        if claims_result and claims_result.claims:
            try:
                from sauron.extraction.condition_checker import check_conditions
                claim_dicts = [
                    {"id": f"{conversation_id}_{c.id}",
                     "claim_text": c.claim_text,
                     "claim_type": c.claim_type}
                    for c in claims_result.claims
                ]
                condition_matches = check_conditions(
                    claim_dicts,
                    conversation_id=conversation_id,
                    db_path=db_path,
                )
            except Exception as e:
                logger.warning("Condition checker failed (non-fatal): %s", e)

        result = {
            "conversation_id": conversation_id,
            "cluster_id": cluster_id,
            "depth_lane": depth_lane,
            "claim_count": claim_count,
            "tier_distribution": tier_dist,
            "processing_status": processing_status,
            "title": title,
            "condition_matches": len(condition_matches),
        }

        logger.info(
            "Text cluster %s → conversation %s: %d claims "
            "(auto=%d, quick=%d, hold=%d), status=%s",
            cluster_id[:8], conversation_id[:16], claim_count,
            tier_dist["auto_route"], tier_dist["quick_review"], tier_dist["hold"],
            processing_status,
        )

        return result

    finally:
        conn.close()


def _build_title(metadata: dict, triage: dict) -> str:
    """Build a display title for the text conversation."""
    display_name = metadata.get("display_name")
    thread_type = metadata.get("thread_type", "")
    summary = triage.get("summary", "")

    if display_name:
        return f"[Text] {display_name}"
    elif summary:
        # Use first ~60 chars of triage summary
        short = summary[:60]
        if len(summary) > 60:
            short += "..."
        return f"[Text] {short}"
    elif thread_type == "group":
        return "[Text] Group conversation"
    else:
        return "[Text] 1:1 conversation"


def _resolve_related_claim_id(
    conversation_id: str,
    raw_related_id: str | None,
) -> str | None:
    """Prefix related_claim_id with conversation_id if it's a bare claim_xxx."""
    if not raw_related_id:
        return None
    if raw_related_id.startswith("claim_"):
        return f"{conversation_id}_{raw_related_id}"
    return raw_related_id


def _store_new_contacts(
    conn: sqlite3.Connection,
    conversation_id: str,
    claims_result: ClaimsResult,
) -> None:
    """Store new contact mentions from text extraction."""
    if not claims_result.new_contacts_mentioned:
        return

    for mention in claims_result.new_contacts_mentioned:
        if isinstance(mention, str):
            name = mention.strip()
            org = None
            context = None
            source_claim_id = None
        else:
            name = (getattr(mention, "name", "") or "").strip()
            org = getattr(mention, "organization", None)
            context = getattr(mention, "context", None)
            source_claim_id = getattr(mention, "source_claim_id", None)

        if not name or len(name) < 2:
            continue

        # Check if already exists in unified_contacts
        existing = conn.execute(
            "SELECT id FROM unified_contacts WHERE LOWER(canonical_name) = ?",
            (name.lower(),),
        ).fetchone()

        if existing:
            continue

        # Check pending_contacts
        pending = conn.execute(
            "SELECT id FROM pending_contacts WHERE LOWER(display_name) = ? AND status = 'pending'",
            (name.lower(),),
        ).fetchone()

        if pending:
            continue

        # Insert into pending_contacts
        pc_id = str(uuid.uuid4())[:8]
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT OR IGNORE INTO pending_contacts
                (id, display_name, source, phone, first_seen_at, thread_ids, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"pc_{pc_id}",
            name,
            "text_extraction",
            "",
            now_iso,
            json.dumps([conversation_id]),
            "pending",
            now_iso,
        ))

        logger.info(
            "New contact flagged from text: %s (org=%s, context=%s)",
            name, org, (context or "")[:50],
        )


def _create_provisional_from_people_mentioned(
    conn: sqlite3.Connection,
    conversation_id: str,
    claims_result: ClaimsResult,
) -> None:
    """Create provisional unified_contacts for people in people_mentioned.

    This mirrors the voice pipeline's _create_provisional_contacts.
    For each person in people_mentioned, if they don't exist in
    unified_contacts, create an unconfirmed entry and link matching claims.
    """
    if not claims_result.people_mentioned:
        return

    created = 0
    linked = 0
    for name in claims_result.people_mentioned:
        if not name or len(name.strip()) < 2:
            continue
        name = name.strip()
        name_lower = name.lower()

        # Skip if already exists
        existing = conn.execute(
            "SELECT id FROM unified_contacts WHERE LOWER(canonical_name) = ?",
            (name_lower,),
        ).fetchone()
        if existing:
            # Still try to link unlinked claims to this contact
            contact_id = dict(existing)["id"]
            matching = conn.execute(
                """SELECT id FROM event_claims
                   WHERE conversation_id = ?
                     AND LOWER(subject_name) = ?
                     AND subject_entity_id IS NULL""",
                (conversation_id, name_lower),
            ).fetchall()
            for claim_row in matching:
                claim_id = dict(claim_row)["id"]
                conn.execute(
                    "UPDATE event_claims SET subject_entity_id = ? WHERE id = ? AND subject_entity_id IS NULL",
                    (contact_id, claim_id),
                )
                # Write claim_entities junction entry
                conn.execute(
                    """INSERT OR IGNORE INTO claim_entities
                       (id, claim_id, entity_id, entity_name, role, confidence, link_source)
                       VALUES (?, ?, ?, ?, 'subject', NULL, 'resolver')""",
                    (str(uuid.uuid4()), claim_id, contact_id, name),
                )
                linked += 1
            continue

        # Check pending_contacts — don't duplicate
        pending = conn.execute(
            "SELECT id FROM pending_contacts WHERE LOWER(display_name) = ? AND status = 'pending'",
            (name_lower,),
        ).fetchone()
        if pending:
            continue

        # Create provisional contact
        contact_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO unified_contacts
               (id, canonical_name, is_confirmed, source_conversation_id, created_at)
               VALUES (?, ?, 0, ?, datetime('now'))""",
            (contact_id, name, conversation_id),
        )
        created += 1

        # Link matching claims
        matching = conn.execute(
            """SELECT id FROM event_claims
               WHERE conversation_id = ?
                 AND LOWER(subject_name) = ?
                 AND subject_entity_id IS NULL""",
            (conversation_id, name_lower),
        ).fetchall()
        for claim_row in matching:
            claim_id = dict(claim_row)["id"]
            conn.execute(
                "UPDATE event_claims SET subject_entity_id = ? WHERE id = ? AND subject_entity_id IS NULL",
                (contact_id, claim_id),
            )
            # Write claim_entities junction entry
            conn.execute(
                """INSERT OR IGNORE INTO claim_entities
                   (id, claim_id, entity_id, entity_name, role, confidence, link_source)
                   VALUES (?, ?, ?, ?, 'subject', NULL, 'resolver')""",
                (str(uuid.uuid4()), claim_id, contact_id, name),
            )
            linked += 1

    if created or linked:
        logger.info(
            "[TextPipeline] Provisional contacts for %s: %d created, %d claims linked",
            conversation_id[:8], created, linked,
        )
