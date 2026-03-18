"""Test sauron/intelligence/beliefs.py -- belief layer utilities."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from sauron.db.tables import ALL_TABLES_SQL


@pytest.fixture
def belief_db(tmp_path, monkeypatch):
    """Create a temp DB with full schema and patch get_connection."""
    db_path = tmp_path / "beliefs_test.db"
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

    import sauron.intelligence.beliefs
    monkeypatch.setattr(sauron.intelligence.beliefs, "get_connection", _factory)

    return db_path


def _seed_belief(db_path, entity_id="contact_1", belief_key="hobby",
                 summary="Likes chess", status="active", confidence=0.8,
                 last_confirmed_at=None):
    """Insert a belief row and return its ID."""
    bid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    last_confirmed = last_confirmed_at or now
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO beliefs
           (id, entity_type, entity_id, belief_key, belief_summary, status,
            confidence, support_count, contradiction_count,
            first_observed_at, last_confirmed_at, last_changed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 2, 0, ?, ?, ?, ?)""",
        (bid, "contact", entity_id, belief_key, summary, status,
         confidence, now, last_confirmed, now, now),
    )
    conn.commit()
    conn.close()
    return bid


def _seed_contact(db_path, contact_id="contact_1", name="Test Person"):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT OR IGNORE INTO unified_contacts
           (id, canonical_name, is_confirmed, created_at)
           VALUES (?, ?, 1, datetime('now'))""",
        (contact_id, name),
    )
    conn.commit()
    conn.close()


# -- detect_stale_beliefs --


def test_detect_stale_beliefs_marks_old(belief_db):
    """Beliefs not confirmed in 90+ days become stale."""
    from sauron.intelligence.beliefs import detect_stale_beliefs, STALENESS_THRESHOLD_DAYS

    old_date = (datetime.now(timezone.utc) - timedelta(days=STALENESS_THRESHOLD_DAYS + 5)).isoformat()
    _seed_belief(belief_db, belief_key="old_hobby", status="active", last_confirmed_at=old_date)

    count = detect_stale_beliefs()
    assert count == 1

    conn = sqlite3.connect(str(belief_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status FROM beliefs WHERE belief_key = ?", ("old_hobby",)).fetchone()
    conn.close()
    assert row["status"] == "stale"


def test_detect_stale_beliefs_skips_recent(belief_db):
    """Beliefs confirmed recently remain unchanged."""
    recent = datetime.now(timezone.utc).isoformat()
    _seed_belief(belief_db, belief_key="recent_hobby", status="active", last_confirmed_at=recent)

    from sauron.intelligence.beliefs import detect_stale_beliefs
    count = detect_stale_beliefs()
    assert count == 0


def test_detect_stale_beliefs_skips_already_stale(belief_db):
    """Beliefs already stale are not re-processed."""
    from sauron.intelligence.beliefs import detect_stale_beliefs, STALENESS_THRESHOLD_DAYS

    old_date = (datetime.now(timezone.utc) - timedelta(days=STALENESS_THRESHOLD_DAYS + 10)).isoformat()
    _seed_belief(belief_db, belief_key="already_stale", status="stale", last_confirmed_at=old_date)

    count = detect_stale_beliefs()
    assert count == 0


# -- get_beliefs_for_contact --


def test_get_beliefs_for_contact_returns_active(belief_db):
    """Returns active beliefs for a contact, ordered by confidence."""
    _seed_contact(belief_db)
    _seed_belief(belief_db, belief_key="hobby", summary="Likes chess", confidence=0.9)
    _seed_belief(belief_db, belief_key="job", summary="Works at CFTC", confidence=0.7)

    from sauron.intelligence.beliefs import get_beliefs_for_contact
    results = get_beliefs_for_contact("contact_1")
    assert len(results) == 2
    assert results[0]["confidence"] >= results[1]["confidence"]


def test_get_beliefs_for_contact_excludes_stale(belief_db):
    """Stale beliefs are excluded from contact queries."""
    _seed_contact(belief_db)
    _seed_belief(belief_db, belief_key="old", status="stale")
    _seed_belief(belief_db, belief_key="current", status="active")

    from sauron.intelligence.beliefs import get_beliefs_for_contact
    results = get_beliefs_for_contact("contact_1")
    assert len(results) == 1
    assert results[0]["belief_key"] == "current"


def test_get_beliefs_for_contact_respects_limit(belief_db):
    """Limit parameter is honored."""
    _seed_contact(belief_db)
    for i in range(5):
        _seed_belief(belief_db, belief_key=f"key_{i}", confidence=0.5 + i * 0.05)

    from sauron.intelligence.beliefs import get_beliefs_for_contact
    results = get_beliefs_for_contact("contact_1", limit=2)
    assert len(results) == 2


# -- get_beliefs_for_topic --


def test_get_beliefs_for_topic_matches_key_and_summary(belief_db):
    """Topic search matches both belief_key and belief_summary."""
    _seed_contact(belief_db, contact_id="c1")
    _seed_belief(belief_db, entity_id="c1", belief_key="defi_opinion", summary="Supports DeFi regulation")
    _seed_belief(belief_db, entity_id="c1", belief_key="hobby", summary="Likes hiking")

    from sauron.intelligence.beliefs import get_beliefs_for_topic
    results = get_beliefs_for_topic("defi")
    assert len(results) >= 1
    assert any("DeFi" in r["belief_summary"] for r in results)


# -- get_contested_beliefs --


def test_get_contested_beliefs_returns_contested(belief_db):
    """Only beliefs with status=contested are returned."""
    _seed_contact(belief_db)
    _seed_belief(belief_db, belief_key="contested_one", status="contested")
    _seed_belief(belief_db, belief_key="active_one", status="active")

    from sauron.intelligence.beliefs import get_contested_beliefs
    results = get_contested_beliefs()
    assert len(results) == 1
    assert results[0]["belief_key"] == "contested_one"


# -- generate_what_changed --


def test_generate_what_changed_detects_new_beliefs(belief_db):
    """New beliefs since last snapshot appear as NEW in summary."""
    _seed_contact(belief_db)
    _seed_belief(belief_db, belief_key="new_fact", summary="Started a company", status="active")

    from sauron.intelligence.beliefs import generate_what_changed
    summary = generate_what_changed("contact", "contact_1", "conv_1")
    assert summary is not None
    assert "NEW" in summary
    assert "Started a company" in summary


def test_generate_what_changed_returns_none_if_unchanged(belief_db):
    """No changes detected returns None."""
    _seed_contact(belief_db)
    _seed_belief(belief_db, belief_key="stable", summary="Same old", status="active")

    from sauron.intelligence.beliefs import generate_what_changed
    # First call creates the initial snapshot
    generate_what_changed("contact", "contact_1", "conv_1")
    # Second call should find no changes
    result = generate_what_changed("contact", "contact_1", "conv_2")
    assert result is None


def test_generate_what_changed_stores_snapshot(belief_db):
    """Snapshot is stored in what_changed_snapshots table."""
    _seed_contact(belief_db)
    _seed_belief(belief_db, belief_key="fact", summary="Knows Python", status="active")

    from sauron.intelligence.beliefs import generate_what_changed
    generate_what_changed("contact", "contact_1", "conv_1")

    conn = sqlite3.connect(str(belief_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM what_changed_snapshots WHERE entity_id = ?",
        ("contact_1",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["entity_type"] == "contact"
    assert float(row["significance"]) > 0


# -- get_what_changed_for_entity --


def test_get_what_changed_for_entity_returns_recent(belief_db):
    """Returns snapshots within the requested time window."""
    _seed_contact(belief_db)
    _seed_belief(belief_db, belief_key="fact1", summary="A", status="active")

    from sauron.intelligence.beliefs import generate_what_changed, get_what_changed_for_entity
    generate_what_changed("contact", "contact_1", "conv_1")

    results = get_what_changed_for_entity("contact", "contact_1", days=30)
    assert len(results) == 1
    assert "change_summary" in results[0]
