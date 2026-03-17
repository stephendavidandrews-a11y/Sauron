"""Tests for review_actions status transitions (Phase 5C)."""

import sqlite3
import uuid
from unittest.mock import patch

import pytest


@pytest.fixture
def review_db(tmp_path):
    """Create a test DB with the review_actions schema subset."""
    db_path = tmp_path / "review_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            processing_status TEXT,
            reviewed_at DATETIME,
            routed_at DATETIME,
            current_stage TEXT,
            stage_detail TEXT,
            run_status TEXT
        );
        CREATE TABLE event_claims (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            review_status TEXT,
            claim_type TEXT,
            claim_text TEXT
        );
        CREATE TABLE correction_events (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            claim_id TEXT,
            error_type TEXT,
            old_value TEXT,
            new_value TEXT,
            correction_source TEXT,
            created_at DATETIME
        );
        CREATE TABLE beliefs (
            id TEXT PRIMARY KEY,
            entity_id TEXT,
            belief_key TEXT,
            status TEXT
        );
        CREATE TABLE belief_evidence (
            id TEXT PRIMARY KEY,
            belief_id TEXT,
            claim_id TEXT,
            evidence_role TEXT
        );
        CREATE TABLE routing_log (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            status TEXT
        );
        CREATE TABLE routing_summaries (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            final_state TEXT,
            created_at TEXT
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def test_mark_reviewed_sets_routing_failed_on_error(review_db, monkeypatch):
    """When routing fails, status should be routing_failed not completed."""
    conn = sqlite3.connect(str(review_db))
    conn.row_factory = sqlite3.Row
    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO conversations (id, processing_status, current_stage, run_status) VALUES (?, ?, ?, ?)",
        (cid, "awaiting_claim_review", "review", "running")
    )
    conn.commit()
    conn.close()

    def mock_get_conn(db_path=None):
        c = sqlite3.connect(str(review_db))
        c.row_factory = sqlite3.Row
        return c

    import sauron.api.review_actions as ra
    monkeypatch.setattr(ra, "get_connection", mock_get_conn)
    # Patch route_extraction at its source module (imported lazily inside mark_reviewed)
    import sauron.routing.router as router_mod
    monkeypatch.setattr(router_mod, "route_extraction", lambda cid, payload: (_ for _ in ()).throw(Exception("routing broke")))

    result = ra.mark_reviewed(cid)

    check = sqlite3.connect(str(review_db))
    check.row_factory = sqlite3.Row
    row = check.execute("SELECT processing_status FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["processing_status"] == "routing_failed"
    check.close()


def test_mark_reviewed_sets_completed_on_success(review_db, monkeypatch):
    """When routing succeeds, status should be completed."""
    conn = sqlite3.connect(str(review_db))
    conn.row_factory = sqlite3.Row
    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO conversations (id, processing_status, current_stage, run_status) VALUES (?, ?, ?, ?)",
        (cid, "awaiting_claim_review", "review", "running")
    )
    conn.commit()
    conn.close()

    def mock_get_conn(db_path=None):
        c = sqlite3.connect(str(review_db))
        c.row_factory = sqlite3.Row
        return c

    import sauron.api.review_actions as ra
    monkeypatch.setattr(ra, "get_connection", mock_get_conn)
    import sauron.routing.router as router_mod
    import sauron.routing.reviewed_payload as rp_mod
    monkeypatch.setattr(rp_mod, "build_reviewed_payload", lambda cid: {})
    monkeypatch.setattr(router_mod, "route_extraction", lambda cid, payload: None)

    result = ra.mark_reviewed(cid)

    check = sqlite3.connect(str(review_db))
    check.row_factory = sqlite3.Row
    row = check.execute("SELECT processing_status FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["processing_status"] == "completed"
    check.close()
