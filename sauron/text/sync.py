"""Text sync orchestrator — end-to-end text pipeline runner.

Reads new messages from the adapter, ingests, clusters, triages,
extracts, and stores claims for review. Designed to run on a schedule
(APScheduler) or on-demand via API.

Flow:
1. Load adapter (IMessageAdapter)
2. Read watermark from text_sync_state
3. Fetch new messages since watermark → list[TextEvent]
4. Ingest: upsert threads + messages in DB (dedup by source_message_id)
5. For unknown phone numbers: upsert into pending_contacts queue
6. Advance watermark (only after successful ingest)
7. For each whitelisted thread with new messages:
   a. Run clustering on thread's messages (overnight-split model)
   b. For each new cluster:
      - Format for Claude
      - Run Haiku triage → assigns depth lane (0/1/2/3)
      - Lane 0/1: store triage result, mark completed
      - Lane 2+: run Sonnet claims extraction
      - Store claims via process_text_cluster
8. Track daily API spend against $10 cap
"""

import json
import logging
import sqlite3

from sauron.db.connection import get_connection as _db_conn
import time
from datetime import datetime, timezone
from pathlib import Path

from sauron.config import DB_PATH
from sauron.text.adapters.imessage import IMessageAdapter
from sauron.text.identity import build_phone_index, check_whitelist, resolve_thread_participants
from sauron.text.ingest import ingest_events, get_sync_watermark, advance_watermark
from sauron.text.cluster import cluster_thread_from_db, store_clusters
from sauron.text.preprocessor import format_cluster_for_extraction, build_text_participant_roster
from sauron.text.text_extraction import triage_text_cluster, extract_text_claims
from sauron.text.text_synthesis import synthesize_text_cluster
from sauron.text.text_pipeline import process_text_cluster


def _resolve_graph_edge_entities(conversation_id: str, db_path=None):
    """Post-resolve graph edge entity IDs after entity resolution has run."""
    from sauron.config import DB_PATH as _DB
    conn = _get_conn(db_path or _DB)
    try:
        edges = conn.execute(
            """SELECT id, from_entity, from_type, to_entity, to_type
               FROM graph_edges
               WHERE source_conversation_id = ?
                 AND (from_entity_id IS NULL OR to_entity_id IS NULL)""",
            (conversation_id,),
        ).fetchall()

        if not edges:
            return

        updated = 0
        for edge in edges:
            from_id, from_table = None, None
            to_id, to_table = None, None

            if edge["from_entity"]:
                name_lower = edge["from_entity"].strip().lower()
                if edge["from_type"] == "person":
                    r = conn.execute(
                        "SELECT id FROM unified_contacts WHERE LOWER(canonical_name) = ?",
                        (name_lower,),
                    ).fetchone()
                    if r:
                        from_id, from_table = r["id"], "unified_contacts"
                else:
                    r = conn.execute(
                        "SELECT id FROM unified_entities WHERE LOWER(canonical_name) = ?",
                        (name_lower,),
                    ).fetchone()
                    if r:
                        from_id, from_table = r["id"], "unified_entities"

            if edge["to_entity"]:
                name_lower = edge["to_entity"].strip().lower()
                if edge["to_type"] == "person":
                    r = conn.execute(
                        "SELECT id FROM unified_contacts WHERE LOWER(canonical_name) = ?",
                        (name_lower,),
                    ).fetchone()
                    if r:
                        to_id, to_table = r["id"], "unified_contacts"
                else:
                    r = conn.execute(
                        "SELECT id FROM unified_entities WHERE LOWER(canonical_name) = ?",
                        (name_lower,),
                    ).fetchone()
                    if r:
                        to_id, to_table = r["id"], "unified_entities"

            if from_id or to_id:
                conn.execute(
                    """UPDATE graph_edges
                       SET from_entity_id=?, from_entity_table=?,
                           to_entity_id=?, to_entity_table=?
                       WHERE id=?""",
                    (from_id, from_table, to_id, to_table, edge["id"]),
                )
                updated += 1

        conn.commit()
        if updated:
            logger.info(
                "[TextSync] Resolved entity IDs for %d graph edges in %s",
                updated, conversation_id[:8],
            )
    finally:
        conn.close()

logger = logging.getLogger(__name__)

# Daily API spend cap (USD). Pipeline halts extraction when exceeded.
DAILY_SPEND_CAP = 10.0

# Approximate costs per model call (USD)
HAIKU_COST_PER_CALL = 0.005
SONNET_COST_PER_CALL = 0.05


def _get_conn(db_path=None) -> sqlite3.Connection:
    """Get a connection with WAL, FK, and busy_timeout pragmas."""
    if db_path is None:
        return _db_conn()
    # Custom path — apply same pragmas as get_connection
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _get_today_spend(db_path=None) -> float:
    """Sum today's extraction costs from the extractions table."""
    conn = _get_conn(db_path)
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = conn.execute("""
            SELECT model_used,
                   COALESCE(SUM(input_tokens), 0) as total_input,
                   COALESCE(SUM(output_tokens), 0) as total_output
            FROM extractions
            WHERE created_at >= ?
            GROUP BY model_used
        """, (today,)).fetchall()

        total_usd = 0.0
        for row in rows:
            model = row["model_used"] or ""
            inp = row["total_input"]
            out = row["total_output"]
            if "haiku" in model:
                total_usd += inp * 0.25 / 1_000_000 + out * 1.25 / 1_000_000
            elif "sonnet" in model:
                total_usd += inp * 3.0 / 1_000_000 + out * 15.0 / 1_000_000
            elif "opus" in model:
                total_usd += inp * 15.0 / 1_000_000 + out * 75.0 / 1_000_000
        return total_usd
    finally:
        conn.close()


def _log_pending_contact(
    conn: sqlite3.Connection,
    phone: str,
    display_name: str | None,
    source: str,
    thread_id: str,
) -> None:
    """Upsert a pending contact for an unknown phone number."""
    now_iso = datetime.now(timezone.utc).isoformat()

    existing = conn.execute(
        "SELECT id, thread_ids, message_count FROM pending_contacts WHERE phone = ? AND source = ?",
        (phone, source),
    ).fetchone()

    if existing:
        # Update existing — add thread_id if not already there
        thread_ids = json.loads(existing["thread_ids"] or "[]")
        if thread_id not in thread_ids:
            thread_ids.append(thread_id)
        conn.execute("""
            UPDATE pending_contacts
            SET thread_ids = ?, last_seen_at = ?,
                message_count = message_count + 1
            WHERE id = ?
        """, (json.dumps(thread_ids), now_iso, existing["id"]))
    else:
        import uuid
        pc_id = f"pc_{str(uuid.uuid4())[:8]}"
        conn.execute("""
            INSERT OR IGNORE INTO pending_contacts
                (id, phone, display_name, source, first_seen_at,
                 last_seen_at, message_count, thread_ids, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pc_id, phone, display_name, source, now_iso,
            now_iso, 1, json.dumps([thread_id]), "pending", now_iso,
        ))


def sync_text(
    source: str = "imessage",
    db_path=None,
    dry_run: bool = False,
) -> dict:
    """Run a full text sync cycle.

    Args:
        source: Adapter source name ('imessage')
        db_path: Optional DB path override
        dry_run: If True, ingest + cluster but skip extraction (no API calls)

    Returns:
        dict with sync results:
        {
            "messages_read": int,
            "messages_ingested": int,
            "threads_with_new_messages": int,
            "clusters_created": int,
            "clusters_extracted": int,
            "clusters_skipped_budget": int,
            "claims_stored": int,
            "pending_contacts_logged": int,
            "daily_spend_usd": float,
            "errors": list[str],
        }
    """
    start_time = time.time()
    errors = []

    result = {
        "messages_read": 0,
        "messages_ingested": 0,
        "threads_with_new_messages": 0,
        "clusters_created": 0,
        "clusters_extracted": 0,
        "clusters_skipped_lane01": 0,
        "clusters_skipped_budget": 0,
        "claims_stored": 0,
        "pending_contacts_logged": 0,
        "daily_spend_usd": 0.0,
        "errors": errors,
        "duration_seconds": 0.0,
    }

    try:
        # 1. Load adapter
        logger.info("[TextSync] Starting sync (source=%s, dry_run=%s)", source, dry_run)
        adapter = IMessageAdapter()

        # 2. Read watermark
        watermark = get_sync_watermark(source, db_path)
        logger.info("[TextSync] Watermark: ROWID > %d", watermark)

        # 3. Fetch new messages
        events = adapter.read_since(watermark_rowid=watermark)
        result["messages_read"] = len(events)

        if not events:
            logger.info("[TextSync] No new messages since watermark %d", watermark)
            result["duration_seconds"] = round(time.time() - start_time, 1)
            return result

        logger.info("[TextSync] Read %d new messages from adapter", len(events))

        # 4. Ingest (dedup by source_message_id)
        ingest_result = ingest_events(events, db_path)
        result["messages_ingested"] = ingest_result.get("inserted", 0)
        logger.info(
            "[TextSync] Ingested: %d inserted, %d skipped (dup), %d errors",
            ingest_result.get("inserted", 0),
            ingest_result.get("skipped_duplicate", 0),
            ingest_result.get("errors", 0),
        )

        # 5. Log unknown contacts + identify threads with new messages
        phone_index = build_phone_index(db_path)
        conn = _get_conn(db_path)
        try:
            # Find threads that received new messages
            threads_touched = set()
            for event in events:
                # Find the thread_id for this event
                thread_row = conn.execute(
                    "SELECT id, participant_phones FROM text_threads WHERE source = ? AND thread_identifier = ?",
                    (source, event.thread_identifier),
                ).fetchone()
                if thread_row:
                    threads_touched.add(thread_row["id"])

                    # Log unknown participants
                    participants = json.loads(thread_row["participant_phones"] or "[]")
                    for phone in participants:
                        if not check_whitelist([phone], phone_index):
                            from sauron.text.identity import _pyobjc_lookup
                            display_name = None
                            try:
                                display_name = _pyobjc_lookup(phone)
                            except Exception:
                                pass
                            _log_pending_contact(conn, phone, display_name, source, thread_row["id"])
                            result["pending_contacts_logged"] += 1

            conn.commit()
        finally:
            conn.close()

        result["threads_with_new_messages"] = len(threads_touched)
        logger.info("[TextSync] %d threads with new messages", len(threads_touched))

        # 6. Advance watermark (after successful ingest)
        max_source_id = max(
            (int(e.source_message_id) for e in events if e.source_message_id.isdigit()),
            default=watermark,
        )
        advance_watermark(source, str(max_source_id), len(events), db_path)
        logger.info("[TextSync] Watermark advanced to %s", max_source_id)

        # 7. Cluster + extract for whitelisted threads
        for thread_id in threads_touched:
            conn = _get_conn(db_path)
            try:
                thread = conn.execute(
                    "SELECT id, thread_type, display_name, participant_phones FROM text_threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
            finally:
                conn.close()

            if not thread:
                continue

            # Check whitelist
            participants = json.loads(thread["participant_phones"] or "[]")
            if not check_whitelist(participants, phone_index):
                logger.debug("[TextSync] Thread %s not whitelisted, skipping", thread_id[:8])
                continue

            # Cluster
            clusters = cluster_thread_from_db(thread_id, db_path=db_path)
            if not clusters:
                continue

            store_result = store_clusters(thread_id, clusters, db_path)
            new_count = store_result.get("stored", 0)
            result["clusters_created"] += new_count

            if new_count == 0:
                continue  # All clusters already existed

            logger.info(
                "[TextSync] Thread %s (%s): %d new clusters",
                thread_id[:8], thread["display_name"] or "1:1", new_count,
            )

            # Process each new cluster
            conn = _get_conn(db_path)
            try:
                # Get clusters that don't have a conversation_id yet (new ones)
                unprocessed = conn.execute("""
                    SELECT id, start_time, end_time, message_count, participant_count
                    FROM text_clusters
                    WHERE thread_id = ? AND conversation_id IS NULL
                    ORDER BY start_time
                """, (thread_id,)).fetchall()
            finally:
                conn.close()

            for cluster_row in unprocessed:
                cid = cluster_row["id"]

                try:
                    _process_single_cluster(
                        cid, thread, phone_index, result, dry_run, db_path
                    )
                except Exception as e:
                    error_msg = f"Cluster {cid[:8]} failed: {e}"
                    logger.error("[TextSync] %s", error_msg)
                    errors.append(error_msg)

    except Exception as e:
        error_msg = f"Sync failed: {e}"
        logger.error("[TextSync] %s", error_msg, exc_info=True)
        errors.append(error_msg)

    result["daily_spend_usd"] = round(_get_today_spend(db_path), 4)
    result["duration_seconds"] = round(time.time() - start_time, 1)

    logger.info(
        "[TextSync] Complete: %d msgs ingested, %d clusters created, "
        "%d extracted, %d claims, $%.4f today, %.1fs",
        result["messages_ingested"], result["clusters_created"],
        result["clusters_extracted"], result["claims_stored"],
        result["daily_spend_usd"], result["duration_seconds"],
    )

    return result


# ── Post-triage lane promotion rules ──────────────────────────────
# Contacts whose clusters should always get Sonnet extraction (Lane 2)
# even if Haiku triage assigns Lane 0 or 1.
LANE_PROMOTION_PHONES = {
    "+16124370032",   # Catherine Cole
    "6124370032",     # Catherine Cole (unnormalized)
}


def _apply_lane_promotions(lane: int, thread: dict, cluster_id: str) -> int:
    """Promote a cluster's lane if it involves a priority contact."""
    if lane >= 2:
        return lane  # already at extraction level

    participants = json.loads(thread["participant_phones"] or "[]")
    for phone in participants:
        if phone in LANE_PROMOTION_PHONES:
            logger.info(
                "[TextSync] Lane %d → 2 promotion for cluster %s (priority contact %s)",
                lane, cluster_id[:8], phone,
            )
            return 2
    return lane


def _process_single_cluster(
    cluster_id: str,
    thread: dict,
    phone_index: dict,
    result: dict,
    dry_run: bool,
    db_path=None,
) -> None:
    """Process a single cluster through triage → extraction → pipeline."""

    # Check daily budget before extraction
    daily_spend = _get_today_spend(db_path)
    if daily_spend >= DAILY_SPEND_CAP:
        logger.warning(
            "[TextSync] Daily spend cap reached ($%.2f >= $%.2f). "
            "Cluster %s queued for tomorrow.",
            daily_spend, DAILY_SPEND_CAP, cluster_id[:8],
        )
        result["clusters_skipped_budget"] += 1
        return

    # Format cluster for extraction
    formatted = format_cluster_for_extraction(cluster_id, phone_index=phone_index, db_path=db_path)

    if not formatted or not formatted.get("transcript"):
        logger.warning("[TextSync] Cluster %s produced empty transcript, skipping", cluster_id[:8])
        return

    metadata = formatted["metadata"]
    roster = build_text_participant_roster(formatted["participant_map"])

    # Triage (always runs — Haiku, ~$0.005)
    logger.info("[TextSync] Triage cluster %s (%d lines)...", cluster_id[:8], formatted["line_count"])
    triage, triage_usage = triage_text_cluster(formatted["transcript"], metadata)

    lane = triage.get("depth_lane", 0)

    # Post-triage lane promotions
    lane = _apply_lane_promotions(lane, thread, cluster_id)

    logger.info(
        "[TextSync] Cluster %s → Lane %d (%s)",
        cluster_id[:8], lane, triage.get("cluster_classification", "?"),
    )

    # Extract (Lane 2+ only, unless dry_run)
    claims_result = None
    if not dry_run and lane >= 2:
        logger.info("[TextSync] Extracting cluster %s (Lane %d)...", cluster_id[:8], lane)
        claims_result, extract_usage = extract_text_claims(
            formatted["transcript"],
            roster,
            metadata,
            triage,
            conversation_id=f"text_{cluster_id}",
        )
        logger.info(
            "[TextSync] Extracted %d claims from cluster %s",
            len(claims_result.claims), cluster_id[:8],
        )
        result["clusters_extracted"] += 1
    elif lane < 2:
        result["clusters_skipped_lane01"] += 1

    # Derive conversation_id early so post-processing can always reference it
    conversation_id = f"text_{cluster_id}"

    # Synthesis (pass 3) — graph_edges, follow_ups, etc. (Lane 2+ only)
    synthesis_result = None
    if not dry_run and lane >= 2 and claims_result and claims_result.claims:
        try:
            synthesis_result, synth_usage = synthesize_text_cluster(
                transcript=formatted["transcript"],
                claims_json=claims_result.model_dump_json(),
                participant_roster=roster,
                metadata=metadata,
                triage=triage,
            )
            # Store as pass 3 in extractions table
            with sqlite3.connect(str(db_path or DB_PATH), timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("""
                    INSERT OR REPLACE INTO extractions
                        (id, conversation_id, pass_number, model_used,
                         extraction_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    f"{conversation_id}_synthesis",
                    conversation_id,
                    3,  # pass 3 = synthesis
                    "sonnet",
                    json.dumps(synthesis_result),
                    datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()

            edge_count = len(synthesis_result.get("graph_edges", []))
            followup_count = len(synthesis_result.get("follow_ups", []))
            logger.info(
                "[TextSync] Synthesis for %s: %d edges, %d follow_ups | %d/%d tokens",
                cluster_id[:8], edge_count, followup_count,
                synth_usage.get("input_tokens", 0),
                synth_usage.get("output_tokens", 0),
            )

            # Store graph_edges in the graph_edges table (for review UI)
            if edge_count > 0:
                import uuid as _uuid
                with sqlite3.connect(str(db_path or DB_PATH), timeout=30) as conn2:
                    conn2.row_factory = sqlite3.Row
                    conn2.execute("PRAGMA journal_mode=WAL")
                    conn2.execute("PRAGMA foreign_keys=ON")
                    conn2.execute("PRAGMA busy_timeout=30000")
                    # Clear old edges for this conversation
                    conn2.execute(
                        "DELETE FROM graph_edges WHERE source_conversation_id = ?",
                        (conversation_id,),
                    )
                    now_iso = datetime.now(timezone.utc).isoformat()
                    for edge in synthesis_result["graph_edges"]:
                        conn2.execute(
                            """INSERT INTO graph_edges
                               (id, from_entity, from_type, to_entity, to_type,
                                edge_type, strength, source_conversation_id, observed_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (str(_uuid.uuid4()),
                             edge.get("from_entity", ""),
                             edge.get("from_type", "person"),
                             edge.get("to_entity", ""),
                             edge.get("to_type", "person"),
                             edge.get("edge_type", "knows"),
                             edge.get("strength", 0.5),
                             conversation_id, now_iso),
                        )
                    conn2.commit()
                    logger.info(
                        "[TextSync] Stored %d graph edges in graph_edges table for %s",
                        edge_count, cluster_id[:8],
                    )
        except Exception:
            logger.exception("[TextSync] Synthesis failed for %s (non-fatal)", cluster_id[:8])

    # Store via pipeline (creates conversations record, event_claims, etc.)
    pipeline_result = process_text_cluster(
        cluster_id=cluster_id,
        triage=triage,
        claims_result=claims_result,
        metadata=metadata,
        db_path=db_path,
    )

    # Post-resolve graph edge entity IDs
    # (edges were stored above BEFORE entity resolution ran in process_text_cluster)
    try:
        _resolve_graph_edge_entities(conversation_id, db_path)
    except Exception:
        logger.exception("[TextSync] Graph edge entity resolution failed (non-fatal)")

    result["claims_stored"] += pipeline_result.get("claim_count", 0)


def run_text_sync_job():
    """Entry point for APScheduler. Wraps sync_text with error handling."""
    try:
        result = sync_text()
        if result["errors"]:
            logger.warning(
                "[TextSyncJob] Completed with %d errors: %s",
                len(result["errors"]), result["errors"],
            )
        else:
            logger.info(
                "[TextSyncJob] OK: %d msgs, %d clusters, %d claims, $%.4f",
                result["messages_ingested"], result["clusters_created"],
                result["claims_stored"], result["daily_spend_usd"],
            )
    except Exception as e:
        logger.error("[TextSyncJob] Failed: %s", e, exc_info=True)
