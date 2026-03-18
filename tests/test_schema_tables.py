"""Test Phase 9 schema decomposition -- tables module and init_db."""

import re
import sqlite3

import pytest

from sauron.db.tables import ALL_TABLES_SQL
from sauron.db.tables.core import CORE_SQL
from sauron.db.tables.speakers import SPEAKERS_SQL
from sauron.db.tables.intelligence import INTELLIGENCE_SQL
from sauron.db.tables.corrections import CORRECTIONS_SQL
from sauron.db.tables.operations import OPERATIONS_SQL
from sauron.db.tables.text import TEXT_SQL
from sauron.db.tables.routing import ROUTING_SQL
from sauron.db.tables.entities import ENTITIES_SQL


def _extract_table_names(sql: str) -> list[str]:
    """Pull CREATE TABLE names from a SQL string."""
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)


# -- ALL_TABLES_SQL completeness --


def test_all_tables_sql_creates_52_tables():
    """ALL_TABLES_SQL must define exactly 52 tables."""
    tables = _extract_table_names(ALL_TABLES_SQL)
    assert len(tables) == 52, f"Expected 52 tables, got {len(tables)}: {tables}"


def test_all_tables_sql_executes_cleanly(tmp_path):
    """ALL_TABLES_SQL can be executed on a fresh DB without errors."""
    db = tmp_path / "fresh.db"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(ALL_TABLES_SQL)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [r[0] for r in rows]
    assert len(table_names) == 52
    conn.close()


def test_all_tables_sql_is_idempotent(tmp_path):
    """Executing ALL_TABLES_SQL twice must not raise."""
    db = tmp_path / "idempotent.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(ALL_TABLES_SQL)
    conn.executescript(ALL_TABLES_SQL)  # second run
    conn.close()


# -- Domain module table counts --


_DOMAIN_EXPECTATIONS = {
    "core": (CORE_SQL, ["conversations", "audio_files", "transcripts", "extractions"]),
    "speakers": (
        SPEAKERS_SQL,
        [
            "vocal_features", "vocal_baselines", "contact_affiliations_cache",
            "provisional_org_suggestions", "voice_profiles", "unified_contacts",
            "voice_samples", "voice_match_log",
        ],
    ),
    "intelligence": (
        INTELLIGENCE_SQL,
        [
            "graph_edges", "policy_positions", "embeddings", "event_episodes",
            "event_claims", "claim_entities", "beliefs", "belief_evidence",
            "what_changed_snapshots", "belief_transitions",
            "belief_resynthesis_proposals",
        ],
    ),
    "corrections": (
        CORRECTIONS_SQL,
        [
            "extraction_corrections", "correction_events", "vocal_overrides",
            "prompt_amendments", "contact_extraction_preferences",
            "search_events", "amendment_effectiveness", "reprocessing_comparisons",
        ],
    ),
    "operations": (
        OPERATIONS_SQL,
        [
            "personal_performance", "retention_log", "meeting_intentions",
            "review_policy_rules", "transcript_annotations",
            "condition_matches", "merge_audit_log",
        ],
    ),
    "text": (
        TEXT_SQL,
        [
            "text_threads", "text_messages", "text_clusters",
            "text_cluster_messages", "text_sync_state", "pending_contacts",
        ],
    ),
    "routing": (
        ROUTING_SQL,
        [
            "routing_log", "routing_summaries", "synthesis_entity_links",
            "pending_object_routes",
        ],
    ),
    "entities": (
        ENTITIES_SQL,
        [
            "unified_entities", "entity_organizations", "entity_legislation",
            "entity_topics",
        ],
    ),
}


@pytest.mark.parametrize("domain", _DOMAIN_EXPECTATIONS.keys())
def test_domain_module_has_expected_tables(domain):
    """Each domain module defines exactly its expected tables."""
    sql, expected = _DOMAIN_EXPECTATIONS[domain]
    actual = _extract_table_names(sql)
    assert sorted(actual) == sorted(expected), (
        f"{domain}: expected {sorted(expected)}, got {sorted(actual)}"
    )


# -- init_db on a temp path --


def test_init_db_creates_all_tables(tmp_path):
    """init_db() on a fresh path should create all 52 tables."""
    from sauron.db.schema import init_db

    db = tmp_path / "init_test.db"
    init_db(db)
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [r[0] for r in rows]
    assert len(table_names) >= 52, f"Only {len(table_names)} tables: {table_names}"
    conn.close()


# -- _verify_schema --


def test_verify_schema_passes_on_fresh_db(tmp_path):
    """_verify_schema should not log errors on a properly initialized DB."""
    from sauron.db.schema import init_db, _verify_schema

    db = tmp_path / "verify_test.db"
    init_db(db)
    _verify_schema(db)


def test_verify_schema_detects_missing_column(tmp_path, caplog):
    """_verify_schema should log an error when a critical column is missing."""
    import logging
    from sauron.db.schema import _verify_schema

    db = tmp_path / "bad.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE graph_edges (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE routing_summaries (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE event_claims (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE unified_contacts (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE transcripts (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE claim_entities (id TEXT PRIMARY KEY)")
    conn.close()

    with caplog.at_level(logging.ERROR, logger="sauron.db.schema"):
        _verify_schema(db)
    assert "SCHEMA VERIFICATION FAILED" in caplog.text
