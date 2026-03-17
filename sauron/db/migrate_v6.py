"""Database migration script for Sauron v6 — Claims-First Architecture.

Adds: event_episodes, event_claims, beliefs, belief_evidence,
      what_changed_snapshots, opportunity_signals, ask_vectors.

All operations are idempotent — safe to run multiple times.

Usage:
    python -m sauron.db.migrate_v6
    # or from code:
    from sauron.db.migrate_v6 import run_v6_migration
    run_v6_migration()
"""

import logging
import sqlite3
from pathlib import Path

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)


V6_TABLES_SQL = """
-- ═══ Event-Centric Extraction (v6 claims-first) ═══

CREATE TABLE IF NOT EXISTS event_episodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    title TEXT,
    episode_type TEXT,
    start_time REAL,
    end_time REAL,
    summary TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS event_claims (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    episode_id TEXT REFERENCES event_episodes(id),
    claim_type TEXT,
    claim_text TEXT NOT NULL,
    subject_entity_id TEXT,
    subject_name TEXT,
    target_entity TEXT,
    speaker_id TEXT,
    modality TEXT,
    polarity TEXT,
    confidence REAL,
    stability TEXT,
    evidence_quote TEXT,
    evidence_start REAL,
    evidence_end REAL,
    review_after DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- ═══ Belief Layer (derived from claims) ═══

CREATE TABLE IF NOT EXISTS beliefs (
    id TEXT PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    belief_key TEXT,
    belief_summary TEXT,
    status TEXT DEFAULT 'provisional',
    confidence REAL,
    support_count INTEGER DEFAULT 0,
    contradiction_count INTEGER DEFAULT 0,
    first_observed_at DATETIME,
    last_confirmed_at DATETIME,
    last_changed_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS belief_evidence (
    id TEXT PRIMARY KEY,
    belief_id TEXT REFERENCES beliefs(id),
    claim_id TEXT REFERENCES event_claims(id),
    weight REAL,
    evidence_role TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS what_changed_snapshots (
    id TEXT PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    snapshot_date DATETIME,
    change_summary TEXT,
    old_state_json TEXT,
    new_state_json TEXT,
    significance REAL,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- ═══ Opportunity Engine (later phases — stub tables) ═══


"""

V6_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_event_episodes_conversation ON event_episodes(conversation_id);
CREATE INDEX IF NOT EXISTS idx_event_episodes_type ON event_episodes(episode_type);
CREATE INDEX IF NOT EXISTS idx_event_claims_conversation ON event_claims(conversation_id);
CREATE INDEX IF NOT EXISTS idx_event_claims_episode ON event_claims(episode_id);
CREATE INDEX IF NOT EXISTS idx_event_claims_type ON event_claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_event_claims_speaker ON event_claims(speaker_id);
CREATE INDEX IF NOT EXISTS idx_event_claims_subject ON event_claims(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_beliefs_entity ON beliefs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_beliefs_key ON beliefs(belief_key);
CREATE INDEX IF NOT EXISTS idx_beliefs_status ON beliefs(status);
CREATE INDEX IF NOT EXISTS idx_belief_evidence_belief ON belief_evidence(belief_id);
CREATE INDEX IF NOT EXISTS idx_belief_evidence_claim ON belief_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_what_changed_entity ON what_changed_snapshots(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_what_changed_date ON what_changed_snapshots(snapshot_date);
"""


def run_v6_migration(db_path: Path = DB_PATH) -> None:
    """Run v6 migrations — adds claims-first tables."""
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}. Run init_db() first.")
        return

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        logger.info("Creating v6 tables (claims-first architecture)...")
        conn.executescript(V6_TABLES_SQL)

        logger.info("Creating v6 indexes...")
        conn.executescript(V6_INDEXES_SQL)

        conn.commit()
        logger.info("v6 migration complete.")

    except Exception:
        conn.rollback()
        logger.exception("v6 migration failed — rolled back.")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Running v6 migration on {DB_PATH} ...")
    run_v6_migration()
    print("Done.")
