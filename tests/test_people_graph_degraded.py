"""Regression test: /people endpoint degrades gracefully when graph_edges lacks typed columns.

Verifies that if graph_edges table exists but without from_type/to_type columns,
the /people endpoint still returns 200 with people data from other sources
(claims, episodes, synthesis links) instead of crashing with 500.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_db_no_graph_types(tmp_path):
    """Create a test DB where graph_edges is missing from_type and to_type columns."""
    db_path = str(tmp_path / "test_sauron.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            source TEXT DEFAULT 'test',
            captured_at TEXT DEFAULT '2026-01-01',
            processing_status TEXT DEFAULT 'awaiting_claim_review',
            reviewed_at TEXT,
            routed_at TEXT
        );
        CREATE TABLE event_episodes (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            title TEXT,
            episode_type TEXT,
            summary TEXT
        );
        CREATE TABLE event_claims (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            episode_id TEXT,
            claim_type TEXT,
            claim_text TEXT,
            subject_entity_id TEXT,
            subject_name TEXT,
            speaker_id TEXT,
            confidence REAL DEFAULT 0.8,
            review_status TEXT DEFAULT 'pending',
            text_user_edited BOOLEAN DEFAULT 0
        );
        CREATE TABLE unified_contacts (
            id TEXT PRIMARY KEY,
            canonical_name TEXT,
            networking_app_contact_id TEXT,
            is_confirmed BOOLEAN DEFAULT 0,
            aliases TEXT,
            relationships TEXT
        );
        CREATE TABLE claim_entities (
            id TEXT PRIMARY KEY,
            claim_id TEXT,
            entity_id TEXT,
            entity_name TEXT,
            entity_table TEXT DEFAULT 'unified_contacts',
            role TEXT DEFAULT 'subject',
            confidence REAL DEFAULT 0.8,
            link_source TEXT DEFAULT 'model'
        );
        CREATE TABLE synthesis_entity_links (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            object_type TEXT,
            object_index INTEGER,
            field_name TEXT,
            original_name TEXT,
            resolved_entity_id TEXT,
            resolution_method TEXT,
            confidence REAL,
            link_source TEXT DEFAULT 'auto_synthesis',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        -- graph_edges WITHOUT from_type and to_type (simulates old/minimal schema)
        CREATE TABLE graph_edges (
            id TEXT PRIMARY KEY,
            from_entity TEXT,
            to_entity TEXT,
            edge_type TEXT,
            strength REAL,
            source_conversation_id TEXT,
            created_at TEXT
        );
        CREATE TABLE extractions (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            pass_number INTEGER DEFAULT 1,
            extraction_json TEXT
        );
        CREATE TABLE routing_summaries (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            final_state TEXT,
            core_lanes TEXT,
            secondary_lanes TEXT,
            pending_entities TEXT,
            warning_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE routing_log (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            status TEXT,
            entity_id TEXT
        );
        CREATE TABLE pending_object_routes (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            entity_id TEXT
        );

        -- Insert test data
        INSERT INTO conversations (id, source, captured_at)
        VALUES ('conv-001', 'test', '2026-01-01T10:00:00');

        INSERT INTO event_episodes (id, conversation_id, title)
        VALUES ('ep-001', 'conv-001', 'Test Episode');

        INSERT INTO unified_contacts (id, canonical_name, is_confirmed)
        VALUES ('contact-001', 'Jane Doe', 1);

        INSERT INTO event_claims (id, conversation_id, episode_id, claim_type, claim_text, subject_entity_id, subject_name)
        VALUES ('claim-001', 'conv-001', 'ep-001', 'factual', 'Jane mentioned the project', 'contact-001', 'Jane Doe');

        -- Graph edge exists but table lacks from_type/to_type columns
        INSERT INTO graph_edges (id, from_entity, to_entity, edge_type, source_conversation_id)
        VALUES ('ge-001', 'Jane Doe', 'John Smith', 'knows', 'conv-001');
    """)
    conn.close()
    return db_path


@pytest.fixture
def client(test_db_no_graph_types, monkeypatch):
    """Create test client with patched DB connection."""
    import sauron.db.connection as db_mod
    from pathlib import Path

    def get_test_connection():
        conn = sqlite3.connect(test_db_no_graph_types, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    monkeypatch.setattr(db_mod, "get_connection", get_test_connection)
    monkeypatch.setattr("sauron.config.DB_PATH", Path(test_db_no_graph_types))

    # Patch all modules that import get_connection directly
    import sauron.api.conversations as conv_mod
    import sauron.api.people_endpoints as people_mod
    monkeypatch.setattr(conv_mod, "get_connection", get_test_connection)
    monkeypatch.setattr(people_mod, "get_connection", get_test_connection)

    monkeypatch.setenv("SAURON_API_KEY", "test-key")
    from sauron.main import app
    client = TestClient(app)
    client.headers["X-API-Key"] = "test-key"
    return client


def test_people_endpoint_degrades_without_graph_types(client):
    """The /people endpoint should return 200 even when graph_edges lacks typed columns."""
    response = client.get("/api/conversations/conv-001/people")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    people = data.get("people", [])

    # Jane Doe should be found from claims (Source 1), even though graph edges failed
    jane = next((p for p in people if "Jane" in str(p.get("canonical_name", "")) or "Jane" in str(p.get("original_names", ""))), None)
    assert jane is not None, f"Jane Doe not found in people response: {people}"


def test_people_endpoint_returns_empty_for_unknown_conversation(client):
    """The /people endpoint should return 200 with empty people for unknown conversation."""
    response = client.get("/api/conversations/nonexistent/people")
    # Should not crash, should return 200 with empty or 404
    assert response.status_code in (200, 404)
