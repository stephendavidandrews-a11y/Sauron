"""V8 migration: Entity resolution + claim linking fixes.

Adds:
- event_claims.display_overrides TEXT (JSON for UI-layer name disambiguation)
- event_claims.review_status TEXT DEFAULT 'unreviewed'
- unified_contacts.source_conversation_id TEXT (provenance for provisional contacts)
- claim_entities junction table (multi-entity linking)
- Migrates existing subject_entity_id data into claim_entities

All operations are idempotent — safe to run multiple times.
"""

import json
import logging
import sqlite3
import uuid
from pathlib import Path

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)

# New columns on existing tables
V8_NEW_COLUMNS = [
    ("event_claims", "display_overrides", "TEXT"),
    ("event_claims", "review_status", "TEXT DEFAULT 'unreviewed'"),
    ("unified_contacts", "source_conversation_id", "TEXT"),
]

# claim_entities junction table
CLAIM_ENTITIES_TABLE = """
CREATE TABLE IF NOT EXISTS claim_entities (
    id TEXT PRIMARY KEY,
    claim_id TEXT REFERENCES event_claims(id) ON DELETE CASCADE,
    entity_id TEXT REFERENCES unified_contacts(id),
    entity_name TEXT,
    role TEXT,
    confidence REAL,
    link_source TEXT DEFAULT 'model',
    created_at DATETIME DEFAULT (datetime('now')),
    UNIQUE(claim_id, entity_id, role)
);
CREATE INDEX IF NOT EXISTS idx_claim_entities_claim ON claim_entities(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_entities_entity ON claim_entities(entity_id);
"""


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check whether a column exists on a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    return column in existing


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check whether a table exists in the database."""
    cursor = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone()[0] > 0


def _add_column_safe(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> bool:
    """Add a column if it does not already exist. Returns True if added."""
    if _column_exists(conn, table, column):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    logger.info(f"  Added column {table}.{column} ({col_type})")
    return True


def run_v8_migration(db_path: Path = DB_PATH) -> None:
    """Run v8 migration: entity resolution fixes."""
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        logger.info("Running v8 migration (entity resolution + claim linking)...")

        # Step 1: Add new columns to existing tables
        added = 0
        for table, col, col_type in V8_NEW_COLUMNS:
            if _add_column_safe(conn, table, col, col_type):
                added += 1
        if added:
            logger.info(f"  Added {added} v8 columns")
        else:
            logger.info("  v8 columns already present")

        # Step 2: Create claim_entities junction table
        conn.executescript(CLAIM_ENTITIES_TABLE)
        logger.info("  claim_entities table created (or already exists)")

        # Step 3: Migrate existing subject_entity_id data into claim_entities
        if _table_exists(conn, "claim_entities"):
            existing_count = conn.execute(
                "SELECT COUNT(*) FROM claim_entities"
            ).fetchone()[0]

            if existing_count == 0:
                # Only migrate if claim_entities is empty (first run)
                linked_claims = conn.execute(
                    """SELECT id, subject_entity_id, subject_name
                       FROM event_claims
                       WHERE subject_entity_id IS NOT NULL
                         AND subject_entity_id != ''"""
                ).fetchall()

                migrated = 0
                for claim in linked_claims:
                    cd = dict(claim)
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO claim_entities
                               (id, claim_id, entity_id, entity_name, role,
                                confidence, link_source)
                               VALUES (?, ?, ?, ?, 'subject', NULL, 'model')""",
                            (str(uuid.uuid4()), cd["id"],
                             cd["subject_entity_id"], cd["subject_name"]),
                        )
                        migrated += 1
                    except sqlite3.IntegrityError:
                        pass  # Skip duplicates

                logger.info(f"  Migrated {migrated} existing entity links to claim_entities")
            else:
                logger.info(f"  claim_entities already has {existing_count} rows, skipping migration")

        conn.commit()
        logger.info("v8 migration complete.")

    except Exception:
        conn.rollback()
        logger.exception("v8 migration failed")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Running v8 migration on {DB_PATH} ...")
    run_v8_migration()
    print("Done.")
