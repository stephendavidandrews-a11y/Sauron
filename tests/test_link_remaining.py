"""Test link-remaining-claims endpoint.

Verifies the user-driven cleanup path for orphaned claims where
subject_entity_id is NULL but a confirmed entity match exists.
"""
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_db(tmp_path):
    """Create a test DB with required tables."""
    db_path = str(tmp_path / "test_link_remaining.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            captured_at TEXT,
            processing_status TEXT DEFAULT 'awaiting_claim_review',
            source_type TEXT DEFAULT 'test',
            reviewed_at TEXT
        );
        CREATE TABLE event_episodes (
            id TEXT PRIMARY KEY,
            conversation_id TEXT
        );
        CREATE TABLE event_claims (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            episode_id TEXT,
            subject_name TEXT,
            subject_entity_id TEXT,
            review_status TEXT,
            text_user_edited INTEGER DEFAULT 0
        );
        CREATE TABLE claim_entities (
            id TEXT PRIMARY KEY,
            claim_id TEXT,
            entity_id TEXT,
            entity_name TEXT,
            role TEXT DEFAULT 'subject',
            confidence REAL,
            link_source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(claim_id, entity_id)
        );
        CREATE TABLE synthesis_entity_links (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            original_name TEXT,
            resolved_entity_id TEXT,
            link_source TEXT,
            confidence REAL
        );
        CREATE TABLE unified_contacts (
            id TEXT PRIMARY KEY,
            canonical_name TEXT,
            is_confirmed INTEGER DEFAULT 1,
            networking_app_contact_id TEXT,
            email TEXT,
            phone_number TEXT,
            aliases TEXT,
            relationships TEXT,
            voice_profile_id TEXT,
            source_conversation_id TEXT,
            created_at TEXT DEFAULT '2024-01-01'
        );
        CREATE TABLE transcripts (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            speaker_id TEXT,
            speaker_label TEXT,
            text TEXT
        );
        CREATE TABLE graph_edges (
            id TEXT PRIMARY KEY,
            from_entity TEXT,
            to_entity TEXT
        );
        CREATE TABLE audio_files (
            id TEXT PRIMARY KEY,
            conversation_id TEXT
        );
        CREATE TABLE embeddings (
            id TEXT PRIMARY KEY,
            conversation_id TEXT
        );
        CREATE TABLE correction_events (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            claim_id TEXT,
            correction_type TEXT,
            old_value TEXT,
            new_value TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.close()
    return db_path


@pytest.fixture
def app_client(test_db, monkeypatch):
    """Create a test client with the test database."""
    import sauron.db.connection as db_mod
    import sauron.api.conversations as conv_mod

    def get_test_connection():
        conn = sqlite3.connect(test_db, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    monkeypatch.setattr(db_mod, "get_connection", get_test_connection)
    monkeypatch.setattr(conv_mod, "get_connection", get_test_connection)

    from sauron.api.conversations import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed(db_path):
    """Seed: Daniel Park with 2 linked + 2 orphaned claims."""
    conn = sqlite3.connect(db_path)
    conv_id = "conv-lr"
    ep_id = "ep-lr"
    entity_id = "ent-daniel"

    conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-01')", (conv_id,))
    conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))
    conn.execute(
        "INSERT INTO unified_contacts (id, canonical_name, is_confirmed) VALUES (?, 'Daniel Park', 1)",
        (entity_id,),
    )

    # 2 linked claims
    for cid in ("claim-1", "claim-2"):
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Daniel Park', ?, 'user_confirmed')",
            (cid, conv_id, ep_id, entity_id),
        )

    # 2 orphaned claims (NULL entity)
    for cid in ("claim-3", "claim-4"):
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Daniel Park', NULL, 'user_confirmed')",
            (cid, conv_id, ep_id),
        )

    # 1 dismissed claim (should not be linked)
    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Daniel Park', NULL, 'dismissed')",
        ("claim-dismissed", conv_id, ep_id),
    )

    conn.commit()
    conn.close()
    return conv_id, entity_id


class TestLinkRemainingClaims:

    def test_links_orphaned_claims(self, test_db, app_client):
        """POST link-remaining-claims fills NULL entity on matching claims."""
        conv_id, entity_id = _seed(test_db)

        resp = app_client.post(
            f"/conversations/{conv_id}/link-remaining-claims",
            json={"entity_id": entity_id, "subject_name": "Daniel Park"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["linked"] == 2  # claim-3 and claim-4

        # Verify DB state
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, subject_entity_id FROM event_claims WHERE id IN ('claim-3', 'claim-4') ORDER BY id"
        ).fetchall()
        for row in rows:
            assert row["subject_entity_id"] == entity_id
        conn.close()

    def test_does_not_touch_already_linked(self, test_db, app_client):
        """Already-linked claims are unaffected."""
        conv_id, entity_id = _seed(test_db)

        app_client.post(
            f"/conversations/{conv_id}/link-remaining-claims",
            json={"entity_id": entity_id, "subject_name": "Daniel Park"},
        )

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, subject_entity_id FROM event_claims WHERE id IN ('claim-1', 'claim-2') ORDER BY id"
        ).fetchall()
        for row in rows:
            assert row["subject_entity_id"] == entity_id  # Was already linked, unchanged
        conn.close()

    def test_skips_dismissed_claims(self, test_db, app_client):
        """Dismissed claims are not linked."""
        conv_id, entity_id = _seed(test_db)

        resp = app_client.post(
            f"/conversations/{conv_id}/link-remaining-claims",
            json={"entity_id": entity_id, "subject_name": "Daniel Park"},
        )
        assert resp.json()["linked"] == 2  # Only claim-3 and claim-4, not claim-dismissed

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT subject_entity_id FROM event_claims WHERE id = 'claim-dismissed'"
        ).fetchone()
        assert row["subject_entity_id"] is None
        conn.close()

    def test_case_insensitive_name_match(self, test_db, app_client):
        """Name matching is case-insensitive."""
        conv_id, entity_id = _seed(test_db)

        # Use lowercase name
        resp = app_client.post(
            f"/conversations/{conv_id}/link-remaining-claims",
            json={"entity_id": entity_id, "subject_name": "daniel park"},
        )
        assert resp.json()["linked"] == 2

    def test_rejects_unconfirmed_entity(self, test_db, app_client):
        """Provisional (unconfirmed) entities are rejected."""
        conn = sqlite3.connect(test_db)
        conv_id = "conv-prov"
        ep_id = "ep-prov"
        provisional_id = "ent-prov"

        conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-02')", (conv_id,))
        conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))
        conn.execute(
            "INSERT INTO unified_contacts (id, canonical_name, is_confirmed) VALUES (?, 'Test', 0)",
            (provisional_id,),
        )
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Test', NULL)",
            ("claim-prov", conv_id, ep_id),
        )
        conn.commit()
        conn.close()

        resp = app_client.post(
            f"/conversations/{conv_id}/link-remaining-claims",
            json={"entity_id": provisional_id, "subject_name": "Test"},
        )
        assert resp.status_code == 400

    def test_no_cross_conversation_linking(self, test_db, app_client):
        """Claims in a different conversation are not affected."""
        conv_id, entity_id = _seed(test_db)

        # Add a claim in a different conversation
        conn = sqlite3.connect(test_db)
        conn.execute("INSERT INTO conversations (id, captured_at) VALUES ('conv-other', '2024-06-02')")
        conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES ('ep-other', 'conv-other')")
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES ('claim-other', 'conv-other', 'ep-other', 'Daniel Park', NULL)",
        )
        conn.commit()
        conn.close()

        app_client.post(
            f"/conversations/{conv_id}/link-remaining-claims",
            json={"entity_id": entity_id, "subject_name": "Daniel Park"},
        )

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT subject_entity_id FROM event_claims WHERE id = 'claim-other'"
        ).fetchone()
        assert row["subject_entity_id"] is None  # Untouched
        conn.close()

    def test_returns_zero_when_nothing_to_link(self, test_db, app_client):
        """No-op when all claims are already linked."""
        conv_id, entity_id = _seed(test_db)

        # Link them first
        app_client.post(
            f"/conversations/{conv_id}/link-remaining-claims",
            json={"entity_id": entity_id, "subject_name": "Daniel Park"},
        )

        # Second call should return 0
        resp = app_client.post(
            f"/conversations/{conv_id}/link-remaining-claims",
            json={"entity_id": entity_id, "subject_name": "Daniel Park"},
        )
        assert resp.json()["linked"] == 0
