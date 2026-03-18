"""Sauron DB schema -- init, verify, and migrate.

Table definitions live in sauron.db.tables.* modules.
"""

import logging
import sqlite3
from pathlib import Path

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialize the sauron.db database with full schema and run migrations."""
    from sauron.db.tables import ALL_TABLES_SQL

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(ALL_TABLES_SQL)
    conn.close()
    logger.info("[MIGRATION] Schema tables created/verified at %s", db_path)

    # Run migrations for existing DBs that may be behind current schema
    from sauron.db.migrate import run_migration
    run_migration(db_path)

    # Post-migration verification: confirm critical columns exist
    _verify_schema(db_path)


def _verify_schema(db_path: Path = DB_PATH) -> None:
    """Post-migration check: verify critical columns exist."""
    critical_columns = [
        ("graph_edges", "from_type"),
        ("graph_edges", "to_type"),
        ("graph_edges", "review_status"),
        ("routing_summaries", "conversation_id"),
        ("routing_summaries", "final_state"),
        ("event_claims", "review_status"),
        ("event_claims", "text_user_edited"),
        ("unified_contacts", "networking_app_contact_id"),
        ("unified_contacts", "relationships"),
        ("unified_contacts", "current_title"),
        ("unified_contacts", "current_organization"),
        ("conversations", "reviewed_at"),
        ("conversations", "routed_at"),
        ("transcripts", "original_text"),
        ("transcripts", "user_corrected"),
        ("event_claims", "subject_type"),
        ("claim_entities", "entity_table"),
        ("graph_edges", "from_entity_id"),
    ]
    conn = sqlite3.connect(str(db_path), timeout=30)
    missing = []
    for table, column in critical_columns:
        try:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            if column not in columns:
                missing.append(f"{table}.{column}")
        except Exception:
            missing.append(f"{table}.{column} (table missing)")
    conn.close()

    if missing:
        logger.error(
            "[MIGRATION] SCHEMA VERIFICATION FAILED -- missing columns: %s",
            ", ".join(missing),
        )
    else:
        logger.info(
            "[MIGRATION] Schema verification passed -- %d critical columns confirmed",
            len(critical_columns),
        )


def migrate_db(db_path: Path = DB_PATH) -> None:
    """Run migrations on an existing database to bring it to current schema.

    Safe to run multiple times (all operations are idempotent).
    For fresh databases, use init_db() instead.
    """
    from sauron.db.migrate import run_migration
    run_migration(db_path)


if __name__ == "__main__":
    init_db()
