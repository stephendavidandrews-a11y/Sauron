"""Test contact bridge resolution logic."""

import uuid
import pytest

from sauron.routing.contact_bridge import (
    resolve_networking_contact_id,
    resolve_entity_networking_id,
)
from tests.helpers import seed_conversation, seed_contact


def test_resolves_primary_non_stephen_contact(test_conn):
    """Resolves the primary non-Stephen contact with correct NA ID."""
    cid = seed_conversation(test_conn, conv_id="conv_bridge1")
    na_id = str(uuid.uuid4())
    eid = seed_contact(test_conn, name="Kyle Thompson", networking_app_contact_id=na_id)

    # Add claims linking this entity
    test_conn.execute(
        """INSERT INTO event_claims (id, conversation_id, claim_type, claim_text,
           subject_entity_id, subject_name, created_at)
           VALUES ('cl1', ?, 'fact', 'Kyle said something', ?, 'Kyle Thompson', datetime('now'))""",
        (cid, eid),
    )
    test_conn.commit()

    result = resolve_networking_contact_id(cid, conn=test_conn)
    assert result is not None
    assert result["resolved"] is True
    assert result["networking_app_contact_id"] == na_id
    assert result["canonical_name"] == "Kyle Thompson"


def test_returns_none_when_only_stephen(test_conn):
    """Returns None when all claims are from Stephen Andrews."""
    cid = seed_conversation(test_conn, conv_id="conv_bridge2")
    eid = seed_contact(test_conn, name="Stephen Andrews", networking_app_contact_id="sa-id")

    test_conn.execute(
        """INSERT INTO event_claims (id, conversation_id, claim_type, claim_text,
           subject_entity_id, subject_name, created_at)
           VALUES ('cl2', ?, 'fact', 'Stephen said something', ?, 'Stephen Andrews', datetime('now'))""",
        (cid, eid),
    )
    test_conn.commit()

    result = resolve_networking_contact_id(cid, conn=test_conn)
    assert result is None


def test_returns_none_when_no_claims(test_conn):
    """Returns None when no claims or speakers exist."""
    cid = seed_conversation(test_conn, conv_id="conv_bridge3")
    result = resolve_networking_contact_id(cid, conn=test_conn)
    assert result is None


def test_unresolved_when_no_networking_id(test_conn):
    """Returns resolved=False when entity has no networking_app_contact_id."""
    cid = seed_conversation(test_conn, conv_id="conv_bridge4")
    eid = seed_contact(test_conn, name="New Person", networking_app_contact_id=None)

    test_conn.execute(
        """INSERT INTO event_claims (id, conversation_id, claim_type, claim_text,
           subject_entity_id, subject_name, created_at)
           VALUES ('cl4', ?, 'fact', 'New Person mentioned', ?, 'New Person', datetime('now'))""",
        (cid, eid),
    )
    test_conn.commit()

    result = resolve_networking_contact_id(cid, conn=test_conn)
    assert result is not None
    assert result["resolved"] is False
    assert result["entity_id"] == eid


def test_fallback_to_transcript_speakers(test_conn):
    """Falls back to transcripts when no claims have subject_entity_id."""
    cid = seed_conversation(test_conn, conv_id="conv_bridge5")
    na_id = str(uuid.uuid4())
    eid = seed_contact(test_conn, name="Jane Doe", networking_app_contact_id=na_id)

    # No claims, but transcript with speaker_id
    test_conn.execute(
        """INSERT INTO transcripts (id, conversation_id, speaker_id, speaker_label,
           start_time, end_time, text, created_at)
           VALUES ('tr1', ?, ?, 'Speaker 1', 0.0, 5.0, 'Hello', datetime('now'))""",
        (cid, eid),
    )
    test_conn.commit()

    result = resolve_networking_contact_id(cid, conn=test_conn)
    assert result is not None
    assert result["resolved"] is True
    assert result["networking_app_contact_id"] == na_id


def test_resolve_entity_networking_id_found(test_conn):
    """resolve_entity_networking_id returns the NA ID when it exists."""
    na_id = str(uuid.uuid4())
    eid = seed_contact(test_conn, name="Found Contact", networking_app_contact_id=na_id)
    result = resolve_entity_networking_id(eid, conn=test_conn)
    assert result == na_id


def test_resolve_entity_networking_id_not_found(test_conn):
    """resolve_entity_networking_id returns None for unknown entity."""
    result = resolve_entity_networking_id("nonexistent-id", conn=test_conn)
    assert result is None
