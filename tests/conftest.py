"""Shared fixtures for Sauron test suite."""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════
# Minimal schema for test DB (routing-focused subset)
# ═══════════════════════════════════════════════════════════════

_SCHEMA = """
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    source TEXT,
    captured_at DATETIME,
    duration_seconds REAL,
    calendar_event_id TEXT,
    context_classification TEXT,
    processing_status TEXT,
    processed_at DATETIME,
    audio_file_id TEXT,
    manual_note TEXT,
    created_at DATETIME,
    reviewed_at DATETIME,
    routed_at DATETIME,
    title TEXT,
    flagged_for_review BOOLEAN,
    modality TEXT,
    current_stage TEXT,
    stage_detail TEXT,
    run_status TEXT,
    blocking_reason TEXT
);

CREATE TABLE routing_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    target_system TEXT,
    route_type TEXT,
    object_class TEXT,
    status TEXT,
    entity_id TEXT,
    attempts INTEGER,
    last_attempt_at DATETIME,
    last_error TEXT,
    payload_json TEXT,
    networking_item_id TEXT,
    created_at DATETIME,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE routing_summaries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    routing_attempt_id TEXT,
    trigger_type TEXT,
    final_state TEXT,
    core_lanes TEXT,
    secondary_lanes TEXT,
    pending_entities TEXT,
    warning_count INTEGER,
    error_count INTEGER,
    created_at TEXT
);

CREATE TABLE unified_contacts (
    id TEXT PRIMARY KEY,
    canonical_name TEXT,
    networking_app_contact_id TEXT,
    cftc_team_member_id INTEGER,
    cftc_stakeholder_id INTEGER,
    voice_profile_id TEXT,
    phone_number TEXT,
    email TEXT,
    calendar_aliases TEXT,
    aliases TEXT,
    is_confirmed BOOLEAN,
    created_at DATETIME,
    relationships TEXT,
    source_conversation_id TEXT,
    current_title TEXT,
    current_organization TEXT,
    title TEXT
);

CREATE TABLE event_claims (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    episode_id TEXT,
    claim_type TEXT,
    claim_text TEXT,
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
    created_at DATETIME,
    importance REAL,
    evidence_type TEXT,
    display_overrides TEXT,
    review_status TEXT,
    firmness TEXT,
    has_specific_action BOOLEAN,
    has_deadline BOOLEAN,
    has_condition BOOLEAN,
    condition_text TEXT,
    direction TEXT,
    time_horizon TEXT,
    text_user_edited BOOLEAN,
    evidence_quality TEXT,
    due_date TEXT,
    date_confidence TEXT,
    date_note TEXT,
    condition_trigger TEXT,
    recurrence TEXT,
    related_claim_id TEXT,
    review_tier TEXT,
    subject_type TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE transcripts (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    speaker_id TEXT,
    speaker_label TEXT,
    start_time REAL,
    end_time REAL,
    text TEXT,
    word_timestamps TEXT,
    created_at DATETIME,
    original_text TEXT,
    user_corrected BOOLEAN,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE event_episodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    title TEXT,
    episode_type TEXT,
    start_time REAL,
    end_time REAL,
    summary TEXT,
    created_at DATETIME,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
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
    link_source TEXT,
    created_at DATETIME
);

CREATE TABLE pending_object_routes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    route_type TEXT,
    payload TEXT,
    blocked_on_entity TEXT,
    created_at TEXT,
    released_at TEXT,
    status TEXT
);

CREATE TABLE unified_entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT,
    canonical_name TEXT,
    aliases TEXT,
    description TEXT,
    first_observed_at TEXT,
    last_observed_at TEXT,
    observation_count INTEGER,
    is_confirmed INTEGER,
    source_conversation_id TEXT,
    created_at DATETIME
);

CREATE TABLE entity_organizations (
    entity_id TEXT PRIMARY KEY,
    industry TEXT,
    org_category TEXT,
    headquarters TEXT,
    parent_org_entity_id TEXT,
    networking_app_org_id TEXT,
    website TEXT
);

CREATE TABLE correction_events (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    episode_id TEXT,
    claim_id TEXT,
    belief_id TEXT,
    error_type TEXT,
    old_value TEXT,
    new_value TEXT,
    user_feedback TEXT,
    correction_source TEXT,
    created_at DATETIME
);

CREATE TABLE claim_entities (
    id TEXT PRIMARY KEY,
    claim_id TEXT,
    entity_id TEXT,
    entity_name TEXT,
    role TEXT,
    confidence REAL,
    link_source TEXT,
    created_at DATETIME,
    entity_table TEXT
);

CREATE TABLE beliefs (
    id TEXT PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    belief_key TEXT,
    belief_summary TEXT,
    status TEXT,
    confidence REAL,
    support_count INTEGER,
    contradiction_count INTEGER,
    first_observed_at DATETIME,
    last_confirmed_at DATETIME,
    last_changed_at DATETIME,
    created_at DATETIME
);

CREATE TABLE belief_evidence (
    id TEXT PRIMARY KEY,
    belief_id TEXT,
    claim_id TEXT,
    weight REAL,
    evidence_role TEXT,
    created_at DATETIME
);

CREATE TABLE extractions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    extraction_json TEXT,
    created_at DATETIME
);

CREATE TABLE voice_profiles (
    id TEXT PRIMARY KEY,
    contact_id TEXT,
    sample_count INTEGER DEFAULT 0,
    confidence_score REAL DEFAULT 0.0,
    created_at DATETIME
);

CREATE TABLE voice_match_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    speaker_label TEXT,
    matched_profile_id TEXT,
    similarity_score REAL,
    match_method TEXT,
    was_correct BOOLEAN,
    created_at DATETIME
);

CREATE TABLE graph_edges (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    from_entity TEXT,
    to_entity TEXT,
    edge_type TEXT,
    strength REAL,
    review_status TEXT DEFAULT 'pending',
    created_at DATETIME
);
"""


@pytest.fixture
def test_db_path(tmp_path):
    """Create an isolated SQLite DB with routing-focused schema subset."""
    db_path = tmp_path / "test_sauron.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    conn.close()
    return db_path


def _make_conn(db_path):
    """Create a new connection to the test DB with proper pragmas."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@pytest.fixture
def test_conn(test_db_path):
    """Open a connection with row_factory + pragmas. Yields; closes on teardown."""
    conn = _make_conn(test_db_path)
    yield conn
    conn.close()


@pytest.fixture
def patch_get_connection(test_db_path, monkeypatch):
    """Patch get_connection at every import site to use test DB.

    Returns the factory function so tests can create additional connections.
    Each call returns a fresh connection to the shared test DB file.
    """
    def _factory(db_path=None):
        return _make_conn(test_db_path)

    # Patch at the source module
    import sauron.db.connection
    monkeypatch.setattr(sauron.db.connection, "get_connection", _factory)

    # Patch at every module that does `from sauron.db.connection import get_connection`
    import sauron.routing.routing_log
    import sauron.routing.contact_bridge
    import sauron.routing.retry
    import sauron.api.conversations
    import sauron.api.review_actions

    for mod in [
        sauron.routing.routing_log,
        sauron.routing.contact_bridge,
        sauron.routing.retry,
        sauron.api.conversations,
        sauron.api.review_actions,
    ]:
        monkeypatch.setattr(mod, "get_connection", _factory)

    return _factory


@pytest.fixture
def app_client(patch_get_connection, monkeypatch):
    """Create a TestClient with patched DB. Does NOT import sauron.main."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    # Import only the router we need — avoids sauron.main triggering
    # module-level DB calls from other API modules (e.g., graph_edges_api).
    from sauron.api.conversations import router as conversations_router
    app.include_router(conversations_router, prefix="/api")

    return TestClient(app)
