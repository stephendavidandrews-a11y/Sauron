"""Database migration script for Sauron v5.

Adds new tables and expands personal_performance without losing data.
All operations are idempotent — safe to run multiple times.

Usage:
    python -m sauron.db.migrate
    # or from code:
    from sauron.db.migrate import run_migration
    run_migration()
"""

import logging
import sqlite3
from pathlib import Path

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)


# ── New tables (CREATE IF NOT EXISTS = idempotent) ─────────────

NEW_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS meeting_intentions (
    id TEXT PRIMARY KEY,
    target_contact_id TEXT,
    conversation_id TEXT REFERENCES conversations(id),
    debrief_conversation_id TEXT REFERENCES conversations(id),
    goals TEXT,
    concerns TEXT,
    strategy TEXT,
    auto_brief TEXT,
    captured_at DATETIME,
    goals_achieved TEXT,
    outcome_notes TEXT,
    unexpected_outcomes TEXT,
    assessed_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prompt_amendments (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    amendment_text TEXT NOT NULL,
    source_analysis TEXT,
    correction_count INTEGER,
    active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contact_extraction_preferences (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    commitment_confidence_threshold REAL,
    typical_follow_through_rate REAL,
    extraction_depth TEXT,
    vocal_alert_sensitivity TEXT,
    relationship_importance REAL,
    custom_notes TEXT,
    last_updated DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    conversation_id TEXT REFERENCES conversations(id),
    contact_id TEXT,
    text_content TEXT NOT NULL,
    embedding BLOB NOT NULL,
    created_at DATETIME DEFAULT (datetime('now'))
);
"""

# ── New indexes ────────────────────────────────────────────────

NEW_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_meeting_intentions_contact ON meeting_intentions(target_contact_id);
CREATE INDEX IF NOT EXISTS idx_meeting_intentions_conversation ON meeting_intentions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_prompt_amendments_active ON prompt_amendments(active);
CREATE INDEX IF NOT EXISTS idx_contact_prefs_contact ON contact_extraction_preferences(contact_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_conversation ON embeddings(conversation_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_contact ON embeddings(contact_id);
"""

# ── personal_performance v1 -> v2 column additions ─────────────
# These are the NEW columns that v5 adds to personal_performance.
# We use ALTER TABLE ADD COLUMN which is a no-op if the column exists
# (we catch the "duplicate column" error).

PERSONAL_PERFORMANCE_NEW_COLUMNS = [
    ("time_of_day", "TEXT"),
    ("day_of_week", "TEXT"),
    ("meetings_prior_today", "INTEGER"),
    ("counterpart_seniority", "TEXT"),
    ("was_planned", "BOOLEAN"),
    ("pitch_mean", "REAL"),
    ("pitch_std", "REAL"),
    ("jitter", "REAL"),                     # existed in v1 already
    ("shimmer", "REAL"),
    ("hnr", "REAL"),
    ("speaking_rate_wpm", "REAL"),
    ("energy_mean", "REAL"),
    ("spectral_centroid", "REAL"),
    ("jitter_vs_baseline", "REAL"),
    ("pitch_std_vs_baseline", "REAL"),
    ("hnr_vs_baseline", "REAL"),
    ("energy_vs_baseline", "REAL"),
    ("talk_time_ratio", "REAL"),
    ("question_count", "INTEGER"),
    ("statement_to_question_ratio", "REAL"),
    ("interruption_count_by_you", "INTEGER"),
    ("interruption_count_of_you", "INTEGER"),
    ("avg_response_latency_ms", "REAL"),
    ("longest_monologue_seconds", "REAL"),
    ("goal_assessment_source", "TEXT"),
    ("outcome_notes", "TEXT"),
    ("coaching_observations", "TEXT"),
]

# Columns from v1 that are being REPLACED by new equivalents:
#   v1 interruption_count  ->  v2 interruption_count_by_you / interruption_count_of_you
#   v1 pitch_authority_score  ->  removed (replaced by raw vocal metrics)
#   v1 energy_level  ->  v2 energy_mean
#   v1 engagement_score  ->  removed
#   v1 pre_meeting_goal  ->  now tracked in meeting_intentions table
#   v1 goal_achieved BOOLEAN  ->  v2 goal_achieved TEXT (richer)
#
# We do NOT drop old columns (SQLite doesn't support DROP COLUMN before 3.35,
# and keeping them is harmless). The old columns will simply go unused.


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check whether a table exists in the database."""
    cursor = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone()[0] > 0


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check whether a column exists on a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    return column in existing


def _add_column_safe(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> bool:
    """Add a column if it does not already exist. Returns True if added."""
    if _column_exists(conn, table, column):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    logger.info(f"  Added column {table}.{column} ({col_type})")
    return True


def _run_v12_titles_and_flags(conn):
    """v12: Add title column to conversations, flagged_for_review column."""
    logger = logging.getLogger(__name__)

    # Add title column
    cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if "title" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN title TEXT")
        logger.info("v12: Added title column to conversations")
    else:
        logger.info("v12: title column already exists")

    # Add flagged_for_review column
    if "flagged_for_review" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN flagged_for_review BOOLEAN DEFAULT 0")
        logger.info("v12: Added flagged_for_review column to conversations")
    else:
        logger.info("v12: flagged_for_review column already exists")


def _run_v11_belief_transitions(conn):
    """v11: Add belief_transitions table for tracking status changes."""
    if not _table_exists(conn, "belief_transitions"):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS belief_transitions (
                id TEXT PRIMARY KEY,
                belief_id TEXT REFERENCES beliefs(id),
                old_status TEXT,
                new_status TEXT,
                driver TEXT,
                source_conversation_id TEXT,
                source_correction_id TEXT,
                cause_summary TEXT,
                created_at DATETIME DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_belief_transitions_belief
                ON belief_transitions(belief_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_belief_transitions_created
                ON belief_transitions(created_at)
        """)
        conn.commit()
        logger.info("v11: Created belief_transitions table")
    else:
        logger.info("v11: belief_transitions table already exists")


def _run_v13_search_events(conn):
    """v13: Add search_events telemetry table."""
    logger = logging.getLogger(__name__)
    if not _table_exists(conn, "search_events"):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS search_events (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                query_type TEXT,
                sections_returned TEXT,
                result_count INTEGER,
                result_clicked TEXT,
                time_to_click_ms INTEGER,
                reformulated BOOLEAN DEFAULT 0,
                session_id TEXT,
                created_at DATETIME DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_search_events_created ON search_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_search_events_query ON search_events(query);
        """)
        logger.info("v13: Created search_events table")
    else:
        logger.info("v13: search_events table already exists")


def _run_v14_iterative_improvement(conn):
    """v14: Add iterative improvement tables (resynthesis, effectiveness, comparisons)."""
    logger = logging.getLogger(__name__)

    # belief_resynthesis_proposals
    if not _table_exists(conn, "belief_resynthesis_proposals"):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS belief_resynthesis_proposals (
                id TEXT PRIMARY KEY,
                belief_id TEXT REFERENCES beliefs(id),
                trigger_correction_id TEXT,
                current_summary TEXT,
                current_status TEXT,
                proposed_summary TEXT,
                proposed_status TEXT,
                proposed_confidence REAL,
                reasoning TEXT,
                status TEXT DEFAULT 'pending',
                resolved_at DATETIME,
                created_at DATETIME DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_resynth_belief ON belief_resynthesis_proposals(belief_id);
            CREATE INDEX IF NOT EXISTS idx_resynth_status ON belief_resynthesis_proposals(status);
        """)
        logger.info("v14: Created belief_resynthesis_proposals table")

    # amendment_effectiveness
    if not _table_exists(conn, "amendment_effectiveness"):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS amendment_effectiveness (
                id TEXT PRIMARY KEY,
                amendment_id TEXT REFERENCES prompt_amendments(id),
                amendment_version TEXT,
                error_type TEXT,
                corrections_before INTEGER,
                corrections_after INTEGER,
                period_days INTEGER,
                effectiveness TEXT,
                computed_at DATETIME DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_amend_eff_amendment ON amendment_effectiveness(amendment_id);
        """)
        logger.info("v14: Created amendment_effectiveness table")

    # reprocessing_comparisons
    if not _table_exists(conn, "reprocessing_comparisons"):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reprocessing_comparisons (
                id TEXT PRIMARY KEY,
                conversation_id TEXT REFERENCES conversations(id),
                old_extraction_id TEXT,
                new_extraction_id TEXT,
                amendment_version TEXT,
                claims_reproduced INTEGER,
                claims_missed INTEGER,
                claims_new INTEGER,
                corrections_resolved INTEGER,
                corrections_regressed INTEGER,
                comparison_json TEXT,
                created_at DATETIME DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_reprocess_conversation ON reprocessing_comparisons(conversation_id);
        """)
        logger.info("v14: Created reprocessing_comparisons table")

    logger.info("v14: Iterative improvement tables ready")


def run_migration(db_path: Path = DB_PATH) -> None:
    """Run all v5 migrations on an existing sauron.db.

    Safe to call repeatedly — every operation checks before acting.
    """
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}. Run init_db() first.")
        return

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        # ── Step 1: Create new tables ──────────────────────────
        logger.info("Creating new v5 tables (if needed)...")
        conn.executescript(NEW_TABLES_SQL)

        # ── Step 2: Expand personal_performance ────────────────
        if _table_exists(conn, "personal_performance"):
            logger.info("Migrating personal_performance to v5 schema...")
            added = 0
            for col_name, col_type in PERSONAL_PERFORMANCE_NEW_COLUMNS:
                if _add_column_safe(conn, "personal_performance", col_name, col_type):
                    added += 1
            if added:
                logger.info(f"  Added {added} new columns to personal_performance")
            else:
                logger.info("  personal_performance already up to date")

            # Migrate goal_achieved from BOOLEAN to TEXT:
            # If old rows have integer 0/1 values, convert them to text.
            # This is safe because TEXT columns accept any value in SQLite.
            conn.execute("""
                UPDATE personal_performance
                SET goal_achieved = CASE
                    WHEN goal_achieved = '1' THEN 'yes'
                    WHEN goal_achieved = '0' THEN 'no'
                    ELSE goal_achieved
                END
                WHERE typeof(goal_achieved) = 'integer'
                   OR goal_achieved IN ('0', '1')
            """)
            conn.commit()
        else:
            logger.info("personal_performance table not found — will be created by init_db()")

        # ── Step 3: Create new indexes ─────────────────────────
        logger.info("Creating new v5 indexes (if needed)...")
        conn.executescript(NEW_INDEXES_SQL)

        # ── Step 4: v6 claim columns ──────────────────────────
        _add_claims_v6_columns(conn)

        # ── Step 5: v7 review + contacts columns ─────────────
        _run_v7_migration(conn)

        # ── Step 6: v8 review pipeline + commitments + voice enrollment ──
        _run_v8_review_and_commitments(conn)

        # ── Step 7: v9 text_user_edited flag ──
        _run_v9_text_user_edited(conn)

        # ── Step 8: v10 pipeline redesign ──
        _run_v10_pipeline_redesign(conn)

        # ── Step 9: v11 belief transitions ──
        _run_v11_belief_transitions(conn)

        # ── Step 10: v12 titles + flags ──
        _run_v12_titles_and_flags(conn)

        # ── Step 11: v13 search telemetry ──
        _run_v13_search_events(conn)

        # ── Step 12: v14 iterative improvement ──
        _run_v14_iterative_improvement(conn)

        # ── Step 13: v15 routing log (Sauron ↔ Networking integration) ──
        _run_v15_routing_log(conn)

        # ── Step 14: v16 synthesis entity links (Entity Resolution Phase 1) ──
        _run_v16_synthesis_entity_links(conn)

        # ── Step 15: v18 routing summaries (degraded-state visibility) ──
        _run_v18_routing_summaries(conn)

        # Wave 2: affiliation cache
        _run_v19_affiliation_cache(conn)

        conn.commit()
        logger.info("Migration complete.")

    except Exception:
        conn.rollback()
        logger.exception("Migration failed — rolled back.")
        raise
    finally:
        conn.close()


def _run_v9_text_user_edited(conn):
    """v9: Add text_user_edited flag to event_claims."""
    logger.info("Running v9 migration (text_user_edited flag)...")
    if _add_column_safe(conn, "event_claims", "text_user_edited", "BOOLEAN DEFAULT 0"):
        logger.info("  Added event_claims.text_user_edited")
    else:
        logger.info("  v9 column already present")
    conn.commit()


def _run_v8_review_and_commitments(conn):
    """v8: Add review pipeline, commitment classification, voice enrollment columns.
    All idempotent via _add_column_safe."""
    logger.info("Running v8 migration (review pipeline + commitments + voice enrollment)...")
    added = 0

    # event_claims: review + commitment columns
    for col, col_type in [
        ("display_overrides", "TEXT"),
        ("review_status", "TEXT"),
        ("firmness", "TEXT"),
        ("has_specific_action", "BOOLEAN"),
        ("has_deadline", "BOOLEAN"),
        ("has_condition", "BOOLEAN"),
        ("condition_text", "TEXT"),
        ("direction", "TEXT"),
        ("time_horizon", "TEXT"),
    ]:
        if _add_column_safe(conn, "event_claims", col, col_type):
            added += 1

    # voice_samples: speaker_label for enrollment matching
    if _add_column_safe(conn, "voice_samples", "speaker_label", "TEXT"):
        added += 1

    # claim_entities junction table
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS claim_entities (
            id TEXT PRIMARY KEY,
            claim_id TEXT REFERENCES event_claims(id) ON DELETE CASCADE,
            entity_id TEXT REFERENCES unified_contacts(id),
            entity_name TEXT,
            role TEXT DEFAULT 'subject',
            confidence REAL,
            link_source TEXT DEFAULT 'model',
            created_at DATETIME DEFAULT (datetime('now')),
            UNIQUE(claim_id, entity_id, role)
        );
        CREATE INDEX IF NOT EXISTS idx_claim_entities_claim ON claim_entities(claim_id);
        CREATE INDEX IF NOT EXISTS idx_claim_entities_entity ON claim_entities(entity_id);
        CREATE INDEX IF NOT EXISTS idx_claim_entities_source ON claim_entities(link_source);
    """)

    if added:
        logger.info(f"  Added {added} v8 columns + claim_entities table")
    else:
        logger.info("  v8 schema already up to date")
    conn.commit()


def _add_claims_v6_columns(conn):
    """Add importance and evidence_type to event_claims (extraction spec update)."""
    cursor = conn.execute("PRAGMA table_info(event_claims)")
    cols = {row[1] for row in cursor.fetchall()}
    if "importance" not in cols:
        conn.execute("ALTER TABLE event_claims ADD COLUMN importance REAL")
    if "evidence_type" not in cols:
        conn.execute("ALTER TABLE event_claims ADD COLUMN evidence_type TEXT")
    conn.commit()


# ── V7: Review surface + contact sync columns ─────────────────

V7_NEW_COLUMNS = [
    ("conversations", "reviewed_at", "DATETIME"),
    ("conversations", "routed_at", "DATETIME"),
    ("transcripts", "original_text", "TEXT"),
    ("transcripts", "user_corrected", "BOOLEAN DEFAULT 0"),
    ("unified_contacts", "relationships", "TEXT"),
]


def _run_v7_migration(conn):
    """Add review surface and contact sync columns."""
    logger.info("Running v7 migration (review + contacts)...")
    added = 0
    for table, col, col_type in V7_NEW_COLUMNS:
        if _add_column_safe(conn, table, col, col_type):
            added += 1
    if added:
        logger.info(f"  Added {added} v7 columns")
    else:
        logger.info("  v7 columns already present")

    # ── v17: pending_object_routes (Category 2, Step C) ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_object_routes (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            route_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            blocked_on_entity TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            released_at TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_routes_entity ON pending_object_routes(blocked_on_entity)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_routes_status ON pending_object_routes(released_at)")

    conn.commit()


def _run_v10_pipeline_redesign(conn):
    """v10: Pipeline redesign -- transcript_annotations table."""
    logger.info("Running v10 migration (pipeline redesign)...")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transcript_annotations (
            id TEXT PRIMARY KEY,
            conversation_id TEXT REFERENCES conversations(id),
            transcript_segment_id TEXT REFERENCES transcripts(id),
            start_char INTEGER NOT NULL,
            end_char INTEGER NOT NULL,
            original_text TEXT NOT NULL,
            resolved_contact_id TEXT REFERENCES unified_contacts(id),
            resolved_name TEXT NOT NULL,
            annotation_type TEXT DEFAULT 'name',
            created_at DATETIME DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_transcript_annotations_conversation
            ON transcript_annotations(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_transcript_annotations_segment
            ON transcript_annotations(transcript_segment_id);
    """)
    logger.info("  transcript_annotations table created (or already exists)")


def _run_v15_routing_log(conn):
    """v15: Add routing_log table for Sauron <-> Networking integration."""
    logger.info("Running v15 migration (routing_log table)...")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS routing_log (
            id TEXT PRIMARY KEY,
            conversation_id TEXT REFERENCES conversations(id),
            target_system TEXT NOT NULL,
            route_type TEXT NOT NULL DEFAULT 'direct_write',
            object_class TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            entity_id TEXT,
            attempts INTEGER DEFAULT 0,
            last_attempt_at DATETIME,
            last_error TEXT,
            payload_json TEXT,
            networking_item_id TEXT,
            created_at DATETIME DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_routing_log_conversation ON routing_log(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_routing_log_status ON routing_log(status);
        CREATE INDEX IF NOT EXISTS idx_routing_log_entity ON routing_log(entity_id);
        CREATE INDEX IF NOT EXISTS idx_routing_log_target ON routing_log(target_system);
    """)
    logger.info("  routing_log table created (or already exists)")



def _run_v16_synthesis_entity_links(conn):
    """v16: Add synthesis_entity_links table for entity resolution Phase 1."""
    logger.info("Running v16 migration (synthesis_entity_links table)...")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS synthesis_entity_links (
            id TEXT PRIMARY KEY,
            conversation_id TEXT REFERENCES conversations(id),
            object_type TEXT NOT NULL,
            object_index INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            resolved_entity_id TEXT,
            resolution_method TEXT,
            confidence REAL,
            link_source TEXT DEFAULT 'auto_synthesis',
            created_at DATETIME DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_sel_conversation ON synthesis_entity_links(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_sel_entity ON synthesis_entity_links(resolved_entity_id);
    """)
    logger.info("  synthesis_entity_links table created (or already exists)")


def _run_v18_routing_summaries(conn):
    """v18: Add routing_summaries table for degraded-state visibility."""
    logger.info("Running v18 migration (routing_summaries table)...")
    if not _table_exists(conn, "routing_summaries"):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS routing_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                routing_attempt_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                final_state TEXT NOT NULL,
                core_lanes TEXT NOT NULL,
                secondary_lanes TEXT NOT NULL,
                pending_entities TEXT,
                warning_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE INDEX IF NOT EXISTS idx_rs_conversation ON routing_summaries(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_rs_state ON routing_summaries(final_state);
        """)
        logger.info("  routing_summaries table created")
    else:
        logger.info("  routing_summaries table already exists")



def _run_v19_affiliation_cache(conn):
    """v19 (Wave 2): Add contact_affiliations_cache table.

    This is a MIRROR of current Networking App affiliation state for synced contacts.
    On each sync per contact:
      - upsert affiliations present in the Networking response
      - delete stale cache rows for that contact no longer in the response
    System of record remains the Networking App.
    """
    logger.info("Running v19 migration (contact_affiliations_cache table)...")
    if not _table_exists(conn, "contact_affiliations_cache"):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS contact_affiliations_cache (
                id TEXT PRIMARY KEY,
                unified_contact_id TEXT NOT NULL REFERENCES unified_contacts(id),
                networking_affiliation_id TEXT NOT NULL UNIQUE,
                networking_org_id TEXT NOT NULL,
                org_name TEXT NOT NULL,
                org_industry TEXT,
                title TEXT,
                department TEXT,
                role_type TEXT,
                is_current BOOLEAN DEFAULT 1,
                start_date TEXT,
                end_date TEXT,
                resolution_source TEXT,
                synced_at DATETIME DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_cac_contact ON contact_affiliations_cache(unified_contact_id);
            CREATE INDEX IF NOT EXISTS idx_cac_org ON contact_affiliations_cache(networking_org_id);
            CREATE INDEX IF NOT EXISTS idx_cac_org_name ON contact_affiliations_cache(org_name);
        """)
        logger.info("  contact_affiliations_cache table created")
    else:
        # Ensure resolution_source column exists (idempotent)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(contact_affiliations_cache)").fetchall()]
        if "resolution_source" not in cols:
            conn.execute("ALTER TABLE contact_affiliations_cache ADD COLUMN resolution_source TEXT")
            logger.info("  Added resolution_source column to contact_affiliations_cache")
        logger.info("  contact_affiliations_cache table already exists")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Running v5 migration on {DB_PATH} ...")
    run_migration()
    print("Done.")
