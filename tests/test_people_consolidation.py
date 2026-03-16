"""Test people consolidation logic in list_conversation_people endpoint.

Verifies that unresolved claims for a person who also has resolved claims
get merged into the resolved entry for display, without mutating the DB.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_db(tmp_path):
    """Create a minimal test database with the required tables."""
    db_path = str(tmp_path / "test_sauron.db")
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
            entity_name TEXT,
            entity_id TEXT,
            entity_table TEXT DEFAULT 'unified_contacts',
            role TEXT,
            link_source TEXT
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
            from_entity TEXT NOT NULL,
            from_type TEXT NOT NULL DEFAULT '',
            to_entity TEXT NOT NULL,
            to_type TEXT NOT NULL DEFAULT '',
            edge_type TEXT,
            strength REAL DEFAULT 0.5,
            source_conversation_id TEXT,
            review_status TEXT,
            from_entity_id TEXT,
            to_entity_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE audio_files (
            id TEXT PRIMARY KEY,
            conversation_id TEXT
        );
        CREATE TABLE embeddings (
            id TEXT PRIMARY KEY,
            conversation_id TEXT
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

    # Patch both the module-level reference AND the local import in conversations.py
    monkeypatch.setattr(db_mod, "get_connection", get_test_connection)
    monkeypatch.setattr(conv_mod, "get_connection", get_test_connection)

    import sauron.api.people_endpoints as people_mod
    monkeypatch.setattr(people_mod, "get_connection", get_test_connection)

    from sauron.api.conversations import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed_mixed_linkage(db_path):
    """Seed a conversation where Daniel Park has 2 linked + 2 unlinked claims,
    and Vijay Menon has 1 linked + 1 unlinked claim."""
    conn = sqlite3.connect(db_path)
    conv_id = "conv-001"
    ep_id = "ep-001"
    daniel_entity = "ent-daniel"
    vijay_entity = "ent-vijay"

    conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-01')", (conv_id,))
    conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))

    conn.execute(
        "INSERT INTO unified_contacts (id, canonical_name, is_confirmed) VALUES (?, 'Daniel Park', 1)",
        (daniel_entity,),
    )
    conn.execute(
        "INSERT INTO unified_contacts (id, canonical_name, is_confirmed) VALUES (?, 'Vijay Menon', 1)",
        (vijay_entity,),
    )

    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Daniel Park', ?)",
        ("claim-d1", conv_id, ep_id, daniel_entity),
    )
    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Daniel Park', ?)",
        ("claim-d2", conv_id, ep_id, daniel_entity),
    )
    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Daniel Park', NULL)",
        ("claim-d3", conv_id, ep_id),
    )
    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Daniel Park', NULL)",
        ("claim-d4", conv_id, ep_id),
    )

    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Vijay Menon', ?)",
        ("claim-v1", conv_id, ep_id, vijay_entity),
    )
    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Vijay Menon', NULL)",
        ("claim-v2", conv_id, ep_id),
    )

    conn.commit()
    conn.close()
    return conv_id


def _seed_unresolved_only(db_path):
    """Seed a conversation where 'Unknown Person' has claims but no resolved contact."""
    conn = sqlite3.connect(db_path)
    conv_id = "conv-002"
    ep_id = "ep-002"

    conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-02')", (conv_id,))
    conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))

    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Unknown Person', NULL)",
        ("claim-u1", conv_id, ep_id),
    )
    conn.execute(
        "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Unknown Person', NULL)",
        ("claim-u2", conv_id, ep_id),
    )

    conn.commit()
    conn.close()
    return conv_id


class TestPeopleConsolidation:
    """Test the unresolved->resolved merge logic in list_conversation_people."""

    def test_mixed_linkage_consolidates(self, test_db, app_client):
        """When a person has both linked and unlinked claims, they appear once
        with correct claim_count and unlinked_claim_count."""
        conv_id = _seed_mixed_linkage(test_db)
        resp = app_client.get(f"/conversations/{conv_id}/people")
        assert resp.status_code == 200
        data = resp.json()
        people = data["people"]

        names = [p["canonical_name"] for p in people]
        assert "Daniel Park" in names
        assert "Vijay Menon" in names
        assert len(people) == 2, f"Expected 2 people, got {len(people)}: {names}"

        daniel = next(p for p in people if p["canonical_name"] == "Daniel Park")
        assert daniel["claim_count"] == 4  # 2 linked + 2 unlinked
        assert daniel["unlinked_claim_count"] == 2

        vijay = next(p for p in people if p["canonical_name"] == "Vijay Menon")
        assert vijay["claim_count"] == 2  # 1 linked + 1 unlinked
        assert vijay["unlinked_claim_count"] == 1

    def test_fully_linked_no_unlinked_count(self, test_db, app_client):
        """When all claims are linked, unlinked_claim_count is 0."""
        conv_id = _seed_mixed_linkage(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute("DELETE FROM event_claims WHERE subject_entity_id IS NULL")
        conn.commit()
        conn.close()

        resp = app_client.get(f"/conversations/{conv_id}/people")
        data = resp.json()
        people = data["people"]

        daniel = next(p for p in people if p["canonical_name"] == "Daniel Park")
        assert daniel["claim_count"] == 2
        assert daniel["unlinked_claim_count"] == 0

    def test_genuinely_unresolved_stays_separate(self, test_db, app_client):
        """A person with no matching resolved contact stays as unresolved."""
        conv_id = _seed_unresolved_only(test_db)
        resp = app_client.get(f"/conversations/{conv_id}/people")
        data = resp.json()
        people = data["people"]

        assert len(people) == 1
        person = people[0]
        assert person["original_name"] == "Unknown Person"
        assert person["entity_id"] is None
        assert person["status"] == "unresolved"
        assert person["claim_count"] == 2
        assert person["unlinked_claim_count"] == 0

    def test_case_insensitive_matching(self, test_db, app_client):
        """Consolidation matches case-insensitively."""
        conn = sqlite3.connect(test_db)
        conv_id = "conv-003"
        ep_id = "ep-003"
        entity_id = "ent-alice"

        conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-03')", (conv_id,))
        conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))
        conn.execute(
            "INSERT INTO unified_contacts (id, canonical_name, is_confirmed) VALUES (?, 'Alice Smith', 1)",
            (entity_id,),
        )
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'Alice Smith', ?)",
            ("claim-a1", conv_id, ep_id, entity_id),
        )
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id) VALUES (?, ?, ?, 'alice smith', NULL)",
            ("claim-a2", conv_id, ep_id),
        )
        conn.commit()
        conn.close()

        resp = app_client.get(f"/conversations/{conv_id}/people")
        data = resp.json()
        people = data["people"]

        assert len(people) == 1
        assert people[0]["canonical_name"] == "Alice Smith"
        assert people[0]["claim_count"] == 2
        assert people[0]["unlinked_claim_count"] == 1

    def test_no_db_mutation(self, test_db, app_client):
        """The consolidation must not change any DB rows."""
        conv_id = _seed_mixed_linkage(test_db)

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        before = [dict(r) for r in conn.execute(
            "SELECT id, subject_entity_id FROM event_claims WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()]
        conn.close()

        resp = app_client.get(f"/conversations/{conv_id}/people")
        assert resp.status_code == 200

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        after = [dict(r) for r in conn.execute(
            "SELECT id, subject_entity_id FROM event_claims WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()]
        conn.close()

        assert before == after, "DB was mutated by the people endpoint!"
