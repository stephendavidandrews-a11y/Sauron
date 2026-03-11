"""Test cascade Step 1 filter: entity linking on text-approved claims.

Verifies that the confirm-person cascade can fill NULL subject_entity_id
on claims that were already text-approved (user_confirmed), which is the
race condition where users bulk-approve claims before confirming people.
"""
import sqlite3
import uuid

import pytest
from sauron.extraction.cascade import cascade_entity_confirmation


@pytest.fixture
def cascade_db(tmp_path):
    """Create a test DB with required tables for cascade testing."""
    db_path = str(tmp_path / "test_cascade.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            captured_at TEXT,
            title TEXT
        );
        CREATE TABLE event_episodes (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            title TEXT
        );
        CREATE TABLE event_claims (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            episode_id TEXT,
            subject_name TEXT,
            subject_entity_id TEXT,
            review_status TEXT,
            claim_text TEXT
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
        CREATE TABLE unified_contacts (
            id TEXT PRIMARY KEY,
            canonical_name TEXT,
            is_confirmed INTEGER DEFAULT 1,
            aliases TEXT
        );
        CREATE TABLE synthesis_entity_links (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            original_name TEXT,
            resolved_entity_id TEXT,
            link_source TEXT,
            confidence REAL
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


def _get_conn(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_race_condition(db_path):
    """Seed the exact race condition: claims bulk-approved before person confirmed.

    Creates 4 Daniel Park claims:
    - claim-d1, claim-d2: linked (entity resolver succeeded at pipeline time)
    - claim-d3, claim-d4: NULL entity, review_status='user_confirmed' (user approved text first)
    """
    conn = _get_conn(db_path)
    conv_id = "conv-race"
    ep_id = "ep-race"
    entity_id = "ent-daniel"

    conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-01')", (conv_id,))
    conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))
    conn.execute(
        "INSERT INTO unified_contacts (id, canonical_name, is_confirmed) VALUES (?, 'Daniel Park', 1)",
        (entity_id,),
    )

    # Two claims already linked at pipeline time
    for cid in ("claim-d1", "claim-d2"):
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Daniel Park', ?, 'user_confirmed')",
            (cid, conv_id, ep_id, entity_id),
        )
        conn.execute(
            "INSERT INTO claim_entities (id, claim_id, entity_id, entity_name, role, link_source) VALUES (?, ?, ?, 'Daniel Park', 'subject', 'resolver')",
            (str(uuid.uuid4()), cid, entity_id),
        )

    # Two claims with NULL entity — text approved but entity never linked
    for cid in ("claim-d3", "claim-d4"):
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Daniel Park', NULL, 'user_confirmed')",
            (cid, conv_id, ep_id),
        )

    conn.commit()
    conn.close()
    return conv_id, entity_id


class TestCascadeFilterFix:
    """Test that the cascade fills NULL entity links on text-approved claims."""

    def test_fills_null_entity_on_user_confirmed_claims(self, cascade_db):
        """The core race condition: claims approved before person confirmed."""
        conv_id, entity_id = _seed_race_condition(cascade_db)
        conn = _get_conn(cascade_db)

        stats = cascade_entity_confirmation(
            conn, entity_id, "Daniel Park", ["Daniel Park"],
            conversation_id=conv_id, source="confirm_person",
        )
        conn.commit()

        # Should have linked the 2 NULL claims
        assert stats["step1_subject_linked"] == 2

        # Verify DB state
        rows = conn.execute(
            "SELECT id, subject_entity_id FROM event_claims WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()
        for row in rows:
            assert row["subject_entity_id"] == entity_id, (
                f"Claim {row['id']} still has subject_entity_id={row['subject_entity_id']}"
            )

        conn.close()

    def test_does_not_overwrite_existing_user_confirmed_link(self, cascade_db):
        """Claims with user_confirmed + non-NULL entity should NOT be overwritten."""
        conn = _get_conn(cascade_db)
        conv_id = "conv-protect"
        ep_id = "ep-protect"
        entity_a = "ent-alice"
        entity_b = "ent-bob"

        conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-02')", (conv_id,))
        conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))
        conn.execute("INSERT INTO unified_contacts (id, canonical_name) VALUES (?, 'Alice')", (entity_a,))
        conn.execute("INSERT INTO unified_contacts (id, canonical_name) VALUES (?, 'Alice')", (entity_b,))

        # Claim already linked to entity_a by user
        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Alice', ?, 'user_confirmed')",
            ("claim-protected", conv_id, ep_id, entity_a),
        )
        conn.commit()

        # Try to cascade with entity_b — should NOT overwrite
        stats = cascade_entity_confirmation(
            conn, entity_b, "Alice", ["Alice"],
            conversation_id=conv_id, source="cascade",
        )
        conn.commit()

        assert stats["step1_subject_linked"] == 0

        row = conn.execute(
            "SELECT subject_entity_id FROM event_claims WHERE id = 'claim-protected'"
        ).fetchone()
        assert row["subject_entity_id"] == entity_a  # Unchanged
        conn.close()

    def test_skips_dismissed_claims(self, cascade_db):
        """Dismissed claims should never be linked."""
        conn = _get_conn(cascade_db)
        conv_id = "conv-dismissed"
        ep_id = "ep-dismissed"
        entity_id = "ent-dismissed"

        conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-03')", (conv_id,))
        conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))
        conn.execute("INSERT INTO unified_contacts (id, canonical_name) VALUES (?, 'Bob')", (entity_id,))

        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Bob', NULL, 'dismissed')",
            ("claim-dismissed", conv_id, ep_id),
        )
        conn.commit()

        stats = cascade_entity_confirmation(
            conn, entity_id, "Bob", ["Bob"],
            conversation_id=conv_id, source="cascade",
        )
        conn.commit()

        assert stats["step1_subject_linked"] == 0

        row = conn.execute(
            "SELECT subject_entity_id FROM event_claims WHERE id = 'claim-dismissed'"
        ).fetchone()
        assert row["subject_entity_id"] is None  # Still NULL
        conn.close()

    def test_fills_null_on_unreviewed_claims(self, cascade_db):
        """Baseline: unreviewed claims with NULL entity should still be linked."""
        conn = _get_conn(cascade_db)
        conv_id = "conv-unreviewed"
        ep_id = "ep-unreviewed"
        entity_id = "ent-unreviewed"

        conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-04')", (conv_id,))
        conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))
        conn.execute("INSERT INTO unified_contacts (id, canonical_name) VALUES (?, 'Carol')", (entity_id,))

        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Carol', NULL, NULL)",
            ("claim-unreviewed", conv_id, ep_id),
        )
        conn.commit()

        stats = cascade_entity_confirmation(
            conn, entity_id, "Carol", ["Carol"],
            conversation_id=conv_id, source="cascade",
        )
        conn.commit()

        assert stats["step1_subject_linked"] == 1

        row = conn.execute(
            "SELECT subject_entity_id FROM event_claims WHERE id = 'claim-unreviewed'"
        ).fetchone()
        assert row["subject_entity_id"] == entity_id
        conn.close()

    def test_overwrites_different_entity_on_unreviewed_claims(self, cascade_db):
        """Unreviewed claims linked to a different entity CAN be overwritten."""
        conn = _get_conn(cascade_db)
        conv_id = "conv-overwrite"
        ep_id = "ep-overwrite"
        old_entity = "ent-old"
        new_entity = "ent-new"

        conn.execute("INSERT INTO conversations (id, captured_at) VALUES (?, '2024-06-05')", (conv_id,))
        conn.execute("INSERT INTO event_episodes (id, conversation_id) VALUES (?, ?)", (ep_id, conv_id))
        conn.execute("INSERT INTO unified_contacts (id, canonical_name) VALUES (?, 'Dave')", (old_entity,))
        conn.execute("INSERT INTO unified_contacts (id, canonical_name) VALUES (?, 'Dave')", (new_entity,))

        conn.execute(
            "INSERT INTO event_claims (id, conversation_id, episode_id, subject_name, subject_entity_id, review_status) VALUES (?, ?, ?, 'Dave', ?, NULL)",
            ("claim-overwrite", conv_id, ep_id, old_entity),
        )
        conn.commit()

        stats = cascade_entity_confirmation(
            conn, new_entity, "Dave", ["Dave"],
            conversation_id=conv_id, source="cascade",
        )
        conn.commit()

        assert stats["step1_subject_linked"] == 1

        row = conn.execute(
            "SELECT subject_entity_id FROM event_claims WHERE id = 'claim-overwrite'"
        ).fetchone()
        assert row["subject_entity_id"] == new_entity
        conn.close()
