"""Test sauron/learning/amendments.py -- amendment analysis and retrieval."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from sauron.db.tables import ALL_TABLES_SQL


@pytest.fixture
def amend_db(tmp_path, monkeypatch):
    """Create a temp DB with full schema and patch get_connection."""
    db_path = tmp_path / "amend_test.db"
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

    import sauron.learning.amendments
    monkeypatch.setattr(sauron.learning.amendments, "get_connection", _factory)

    return db_path


def _insert_amendment(db_path, version="v1", text="Do not X", active=True,
                      source_analysis=None, created_at=None):
    """Insert a prompt_amendments row."""
    aid = str(uuid.uuid4())
    now = created_at or datetime.now(timezone.utc).isoformat()
    sa = source_analysis or json.dumps({"patterns_addressed": [], "correction_ids": []})
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO prompt_amendments
           (id, version, amendment_text, source_analysis, correction_count, active, created_at)
           VALUES (?, ?, ?, ?, 0, ?, ?)""",
        (aid, version, text, sa, active, now),
    )
    conn.commit()
    conn.close()
    return aid


def _insert_correction_event(db_path, error_type="wrong_claim_type",
                              old_value="X", new_value="Y", created_at=None):
    """Insert a correction_events row."""
    cid = str(uuid.uuid4())
    now = created_at or datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO correction_events
           (id, conversation_id, error_type, old_value, new_value, created_at)
           VALUES (?, 'conv_1', ?, ?, ?, ?)""",
        (cid, error_type, old_value, new_value, now),
    )
    conn.commit()
    conn.close()
    return cid


# -- get_active_amendment --


def test_get_active_amendment_returns_text(amend_db):
    """Returns the amendment text for the active amendment."""
    _insert_amendment(amend_db, version="v1", text="Rule: never do X", active=True)

    from sauron.learning.amendments import get_active_amendment
    result = get_active_amendment()
    assert result == "Rule: never do X"


def test_get_active_amendment_returns_none_when_empty(amend_db):
    """Returns None when no amendments exist."""
    from sauron.learning.amendments import get_active_amendment
    assert get_active_amendment() is None


def test_get_active_amendment_ignores_inactive(amend_db):
    """Inactive amendments are not returned."""
    _insert_amendment(amend_db, version="v1", text="Old rule", active=False)

    from sauron.learning.amendments import get_active_amendment
    assert get_active_amendment() is None


# -- _get_unprocessed_corrections --


def test_get_unprocessed_corrections_after_amendment(amend_db):
    """Only corrections created after the latest amendment are returned."""
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _insert_amendment(amend_db, version="v1", text="Rule A", created_at=past)

    # This correction is AFTER the amendment
    _insert_correction_event(amend_db, error_type="wrong_claim_type")

    from sauron.learning.amendments import _get_unprocessed_corrections
    conn = sqlite3.connect(str(amend_db))
    conn.row_factory = sqlite3.Row
    results = _get_unprocessed_corrections(conn)
    conn.close()
    assert len(results) >= 1


def test_get_unprocessed_corrections_excludes_old(amend_db):
    """Corrections before the latest amendment are excluded."""
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    _insert_correction_event(amend_db, error_type="old_error", created_at=old)

    # Amendment created AFTER the correction
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _insert_amendment(amend_db, version="v1", text="Rule B", created_at=recent)

    from sauron.learning.amendments import _get_unprocessed_corrections
    conn = sqlite3.connect(str(amend_db))
    conn.row_factory = sqlite3.Row
    results = _get_unprocessed_corrections(conn)
    conn.close()
    assert len(results) == 0


# -- _group_corrections --


def test_group_corrections_groups_by_type(amend_db):
    """Corrections are grouped by error type."""
    from sauron.learning.amendments import _group_corrections

    corrections = [
        {"correction_type": "wrong_claim_type", "corrected_at": datetime.now(timezone.utc).isoformat()},
        {"correction_type": "wrong_claim_type", "corrected_at": datetime.now(timezone.utc).isoformat()},
        {"correction_type": "wrong_confidence", "corrected_at": datetime.now(timezone.utc).isoformat()},
    ]
    result = _group_corrections(corrections)
    assert "wrong_claim_type" in result["groups"]
    assert len(result["groups"]["wrong_claim_type"]) == 2
    assert "wrong_confidence" in result["groups"]


def test_group_corrections_ema_decay(amend_db):
    """Old corrections get lower weight than recent ones."""
    from sauron.learning.amendments import _group_corrections, _EMA_HALFLIFE_DAYS

    old = (datetime.now(timezone.utc) - timedelta(days=_EMA_HALFLIFE_DAYS)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()

    corrections = [
        {"correction_type": "test_type", "corrected_at": old},
        {"correction_type": "test_type", "corrected_at": recent},
    ]
    result = _group_corrections(corrections)
    # Two corrections: one weighted ~0.5, one weighted ~1.0 => ~1.5
    wc = result["weighted_counts"]["test_type"]
    assert 1.0 < wc < 2.0, f"Expected ~1.5, got {wc}"


def test_group_corrections_user_feedback_boost(amend_db):
    """Corrections with user_feedback get 2x weight."""
    from sauron.learning.amendments import _group_corrections

    now = datetime.now(timezone.utc).isoformat()
    corrections = [
        {"correction_type": "type_a", "corrected_at": now, "user_feedback": "This was wrong"},
    ]
    result = _group_corrections(corrections)
    # 1 correction with 2x boost = ~2.0
    wc = result["weighted_counts"]["type_a"]
    assert wc >= 1.9


# -- _get_current_version_number --


def test_get_current_version_number_empty(amend_db):
    from sauron.learning.amendments import _get_current_version_number
    conn = sqlite3.connect(str(amend_db))
    conn.row_factory = sqlite3.Row
    assert _get_current_version_number(conn) == 0
    conn.close()


def test_get_current_version_number_parses_v_prefix(amend_db):
    _insert_amendment(amend_db, version="v3", text="Rule C")

    from sauron.learning.amendments import _get_current_version_number
    conn = sqlite3.connect(str(amend_db))
    conn.row_factory = sqlite3.Row
    assert _get_current_version_number(conn) == 3
    conn.close()


# -- get_contact_preferences --


def test_get_contact_preferences_returns_none_if_missing(amend_db):
    from sauron.learning.amendments import get_contact_preferences
    assert get_contact_preferences("nonexistent") is None


def test_update_and_get_contact_preferences(amend_db):
    from sauron.learning.amendments import update_contact_preference, get_contact_preferences

    update_contact_preference("contact_1", "extraction_depth", "deep")
    prefs = get_contact_preferences("contact_1")
    assert prefs is not None
    assert prefs["extraction_depth"] == "deep"


def test_update_contact_preference_rejects_invalid_field(amend_db):
    from sauron.learning.amendments import update_contact_preference

    with pytest.raises(ValueError, match="Invalid preference field"):
        update_contact_preference("contact_1", "nonexistent_field", "value")


def test_update_contact_preference_upserts(amend_db):
    """Updating the same field twice should overwrite."""
    from sauron.learning.amendments import update_contact_preference, get_contact_preferences

    update_contact_preference("contact_1", "extraction_depth", "shallow")
    update_contact_preference("contact_1", "extraction_depth", "deep")
    prefs = get_contact_preferences("contact_1")
    assert prefs["extraction_depth"] == "deep"


# -- analyze_corrections_and_amend (with mocked Claude) --


def test_analyze_corrections_and_amend_returns_none_when_no_corrections(amend_db):
    """Returns None when there are no unprocessed corrections."""
    from sauron.learning.amendments import analyze_corrections_and_amend
    assert analyze_corrections_and_amend() is None


def test_analyze_corrections_and_amend_below_threshold(amend_db):
    """Returns None when corrections exist but below generalization threshold."""
    # Insert 2 corrections of a slow type (needs 5)
    for _ in range(2):
        _insert_correction_event(amend_db, error_type="rare_error")

    from sauron.learning.amendments import analyze_corrections_and_amend
    assert analyze_corrections_and_amend() is None


def test_analyze_corrections_and_amend_calls_claude(amend_db, monkeypatch):
    """When above threshold, calls Claude and stores new amendment."""
    # Insert enough corrections of a fast type (threshold=3)
    for _ in range(4):
        _insert_correction_event(amend_db, error_type="wrong_claim_type")

    # Mock the Anthropic client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="NEW RULE: Always classify correctly")]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    import sauron.learning.amendments
    monkeypatch.setattr(sauron.learning.amendments, "_client", mock_client)
    monkeypatch.setattr(sauron.learning.amendments, "_get_client", lambda: mock_client)

    from sauron.learning.amendments import analyze_corrections_and_amend
    result = analyze_corrections_and_amend()

    assert result == "NEW RULE: Always classify correctly"
    mock_client.messages.create.assert_called_once()

    # Verify the amendment was stored in DB
    conn = sqlite3.connect(str(amend_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM prompt_amendments WHERE active = TRUE"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["version"] == "v1"
    assert "Always classify" in row["amendment_text"]


# -- _get_amendment_for_pass --


def test_get_amendment_for_pass_filters_by_target(amend_db):
    """Returns only amendments matching the target_pass."""
    conn = sqlite3.connect(str(amend_db))
    conn.execute(
        """INSERT INTO prompt_amendments
           (id, version, amendment_text, active, target_pass, created_at)
           VALUES ('a1', 'v1', 'Claims rule', TRUE, 'claims', datetime('now'))""",
    )
    conn.execute(
        """INSERT INTO prompt_amendments
           (id, version, amendment_text, active, target_pass, created_at)
           VALUES ('a2', 'v1', 'Triage rule', TRUE, 'triage', datetime('now'))""",
    )
    conn.commit()
    conn.close()

    from sauron.learning.amendments import _get_amendment_for_pass
    result = _get_amendment_for_pass("claims")
    assert result == "Claims rule"
