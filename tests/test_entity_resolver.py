"""Test sauron/extraction/entity_resolver.py -- name resolution logic."""

import json
import sqlite3
import uuid

import pytest

from sauron.db.tables import ALL_TABLES_SQL


@pytest.fixture
def resolver_db(tmp_path, monkeypatch):
    """Create a temp DB with full schema and patch get_connection."""
    db_path = tmp_path / "resolver_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(ALL_TABLES_SQL)
    conn.close()

    def _factory(db_path_arg=None):
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    import sauron.db.connection
    monkeypatch.setattr(sauron.db.connection, "get_connection", _factory)

    import sauron.extraction.entity_resolver
    monkeypatch.setattr(sauron.extraction.entity_resolver, "get_connection", _factory)

    return db_path


def _seed(db_path, contacts=None, claims=None, conversation_id="conv_1"):
    """Seed the DB with contacts and claims for resolution testing."""
    conn = sqlite3.connect(str(db_path))

    # Create the conversation
    conn.execute(
        """INSERT OR IGNORE INTO conversations
           (id, source, captured_at, processing_status, modality, created_at)
           VALUES (?, 'test', datetime('now'), 'processed', 'audio', datetime('now'))""",
        (conversation_id,),
    )

    # Insert contacts
    for c in (contacts or []):
        conn.execute(
            """INSERT OR IGNORE INTO unified_contacts
               (id, canonical_name, aliases, relationships, is_confirmed, created_at)
               VALUES (?, ?, ?, ?, 1, datetime('now'))""",
            (c["id"], c["name"], c.get("aliases", ""), c.get("relationships", "")),
        )

    # Insert claims
    for cl in (claims or []):
        conn.execute(
            """INSERT INTO event_claims
               (id, conversation_id, claim_type, claim_text, subject_name,
                subject_entity_id, review_status, created_at)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, datetime('now'))""",
            (cl["id"], conversation_id, cl.get("claim_type", "observation"),
             cl.get("claim_text", "test claim"), cl["subject_name"]),
        )

    conn.commit()
    conn.close()


# -- Direct name match --


def test_resolves_full_name_match(resolver_db):
    """Full canonical name match resolves the entity."""
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "John Smith"},
    ], claims=[
        {"id": "claim_1", "subject_name": "John Smith", "claim_text": "John Smith likes hiking"},
    ])

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["resolved"] == 1

    conn = sqlite3.connect(str(resolver_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT subject_entity_id FROM event_claims WHERE id = 'claim_1'").fetchone()
    conn.close()
    assert row["subject_entity_id"] == "c1"


def test_resolves_case_insensitive(resolver_db):
    """Name matching is case-insensitive."""
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "John Smith"},
    ], claims=[
        {"id": "claim_1", "subject_name": "john smith", "claim_text": "john smith said something"},
    ])

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["resolved"] == 1


# -- Alias match --


def test_resolves_via_alias(resolver_db):
    """Alias-based matching resolves the entity."""
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "Jonathan Smith", "aliases": "John;Johnny"},
    ], claims=[
        {"id": "claim_1", "subject_name": "Johnny",
         "claim_text": "Jonathan Smith goes by Johnny"},
    ])

    # Also seed a transcript to satisfy _verify_conversation_connection for first-name match
    conn = sqlite3.connect(str(resolver_db))
    conn.execute(
        """INSERT INTO transcripts
           (id, conversation_id, speaker_id, text, created_at)
           VALUES ('t1', 'conv_1', 'c1', 'test', datetime('now'))""",
    )
    conn.commit()
    conn.close()

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["resolved"] == 1


# -- Ambiguous match --


def test_ambiguous_name_is_not_resolved(resolver_db):
    """When multiple contacts share a name, mark as ambiguous."""
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "John Smith"},
        {"id": "c2", "name": "John Adams"},
    ], claims=[
        {"id": "claim_1", "subject_name": "John", "claim_text": "John said hello"},
    ])

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    # "John" matches first name of both contacts -> ambiguous
    assert stats["ambiguous"] >= 1 or stats["unresolved"] >= 1
    assert stats["resolved"] == 0


# -- Unresolved --


def test_unknown_name_is_unresolved(resolver_db):
    """Names not matching any contact are counted as unresolved."""
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "John Smith"},
    ], claims=[
        {"id": "claim_1", "subject_name": "Alice Wonderland",
         "claim_text": "Alice Wonderland mentioned something"},
    ])

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["unresolved"] == 1
    assert stats["resolved"] == 0


# -- User correction protection --


def test_skips_user_corrected_claims(resolver_db):
    """Claims with review_status='user_corrected' are never touched."""
    conn = sqlite3.connect(str(resolver_db))
    conn.execute(
        """INSERT INTO conversations
           (id, source, captured_at, processing_status, modality, created_at)
           VALUES ('conv_1', 'test', datetime('now'), 'processed', 'audio', datetime('now'))""",
    )
    conn.execute(
        """INSERT INTO unified_contacts
           (id, canonical_name, is_confirmed, created_at)
           VALUES ('c1', 'John Smith', 1, datetime('now'))""",
    )
    conn.execute(
        """INSERT INTO event_claims
           (id, conversation_id, claim_type, claim_text, subject_name,
            subject_entity_id, review_status, created_at)
           VALUES ('claim_1', 'conv_1', 'observation', 'John Smith test',
                   'John Smith', NULL, 'user_corrected', datetime('now'))""",
    )
    conn.commit()
    conn.close()

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["resolved"] == 0
    assert stats["skipped_user"] >= 0


def test_skips_claims_with_user_linked_entities(resolver_db):
    """Claims with link_source='user' in claim_entities are skipped."""
    conn = sqlite3.connect(str(resolver_db))
    conn.execute(
        """INSERT INTO conversations
           (id, source, captured_at, processing_status, modality, created_at)
           VALUES ('conv_1', 'test', datetime('now'), 'processed', 'audio', datetime('now'))""",
    )
    conn.execute(
        """INSERT INTO unified_contacts
           (id, canonical_name, is_confirmed, created_at)
           VALUES ('c1', 'John Smith', 1, datetime('now'))""",
    )
    conn.execute(
        """INSERT INTO event_claims
           (id, conversation_id, claim_type, claim_text, subject_name,
            subject_entity_id, review_status, created_at)
           VALUES ('claim_1', 'conv_1', 'observation', 'John Smith test',
                   'John Smith', NULL, NULL, datetime('now'))""",
    )
    # User-linked entity in claim_entities
    conn.execute(
        """INSERT INTO claim_entities
           (id, claim_id, entity_id, entity_name, role, link_source, created_at)
           VALUES ('ce1', 'claim_1', 'c1', 'John Smith', 'subject', 'user', datetime('now'))""",
    )
    conn.commit()
    conn.close()

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["skipped_user"] >= 1


# -- Creates claim_entities on resolution --


def test_creates_claim_entities_row_on_resolve(resolver_db):
    """Resolution creates a claim_entities junction row."""
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "John Smith"},
    ], claims=[
        {"id": "claim_1", "subject_name": "John Smith",
         "claim_text": "John Smith likes hiking"},
    ])

    from sauron.extraction.entity_resolver import resolve_claim_entities
    resolve_claim_entities("conv_1")

    conn = sqlite3.connect(str(resolver_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM claim_entities WHERE claim_id = 'claim_1' AND role = 'subject'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["entity_id"] == "c1"
    assert row["link_source"] == "resolver"


# -- First-name-only gating --


def test_first_name_only_requires_conversation_connection(resolver_db):
    """First-name match without conversation connection is gated (ambiguous)."""
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "Alice Johnson"},
    ], claims=[
        {"id": "claim_1", "subject_name": "Alice",
         "claim_text": "Alice mentioned something"},
    ])
    # No transcript, no calendar event linking Alice -> conv_1

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    # Should be ambiguous due to first-name-only gating
    assert stats["resolved"] == 0
    assert stats["ambiguous"] >= 1


def test_first_name_resolves_with_speaker_connection(resolver_db):
    """First-name match with speaker connection resolves."""
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "Alice Johnson"},
    ], claims=[
        {"id": "claim_1", "subject_name": "Alice",
         "claim_text": "Alice mentioned something"},
    ])

    # Add a transcript linking this contact as speaker
    conn = sqlite3.connect(str(resolver_db))
    conn.execute(
        """INSERT INTO transcripts
           (id, conversation_id, speaker_id, text, created_at)
           VALUES ('t1', 'conv_1', 'c1', 'hello', datetime('now'))""",
    )
    conn.commit()
    conn.close()

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["resolved"] == 1


# -- Relational term match --


def test_relational_term_resolves_single_match(resolver_db):
    """Relational term 'my brother' resolves when exactly one contact matches."""
    rels = json.dumps({"relation_to_stephen": "brother"})
    _seed(resolver_db, contacts=[
        {"id": "c1", "name": "Mike Andrews", "relationships": rels},
    ], claims=[
        {"id": "claim_1", "subject_name": "my brother",
         "claim_text": "my brother mentioned plans"},
    ])

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["resolved"] == 1

    conn = sqlite3.connect(str(resolver_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT subject_entity_id FROM event_claims WHERE id = 'claim_1'").fetchone()
    conn.close()
    assert row["subject_entity_id"] == "c1"


# -- No claims to resolve --


def test_no_claims_returns_empty_stats(resolver_db):
    """When no unlinked claims exist, return zero stats."""
    conn = sqlite3.connect(str(resolver_db))
    conn.execute(
        """INSERT INTO conversations
           (id, source, captured_at, processing_status, modality, created_at)
           VALUES ('conv_1', 'test', datetime('now'), 'processed', 'audio', datetime('now'))""",
    )
    conn.commit()
    conn.close()

    from sauron.extraction.entity_resolver import resolve_claim_entities
    stats = resolve_claim_entities("conv_1")
    assert stats["resolved"] == 0
    assert stats["ambiguous"] == 0
    assert stats["unresolved"] == 0
