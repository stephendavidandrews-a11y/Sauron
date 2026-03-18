"""Test sauron/speakers/profiles.py -- voice profile CRUD and validation."""

import sqlite3
import uuid

import numpy as np
import pytest

from sauron.db.tables import ALL_TABLES_SQL


@pytest.fixture
def profile_db(tmp_path, monkeypatch):
    """Create a temp DB with full schema and patch get_connection."""
    db_path = tmp_path / "profiles_test.db"
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

    import sauron.speakers.profiles
    monkeypatch.setattr(sauron.speakers.profiles, "get_connection", _factory)

    # Seed a contact and conversations for FK references
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO unified_contacts (id, canonical_name, is_confirmed, created_at)
           VALUES ('contact_1', 'Alice Smith', 1, datetime('now'))""",
    )
    conn.execute(
        """INSERT INTO conversations (id, source, captured_at, processing_status, created_at)
           VALUES ('conv_2', 'test', datetime('now'), 'processed', datetime('now'))""",
    )
    conn.commit()
    conn.close()

    return db_path


def _random_embedding(dim=192):
    """Generate a random normalized float32 embedding."""
    emb = np.random.randn(dim).astype(np.float32)
    emb /= np.linalg.norm(emb)
    return emb


# -- _validate_embedding --


def test_validate_embedding_rejects_empty():
    from sauron.speakers.profiles import _validate_embedding
    with pytest.raises(ValueError, match="Empty"):
        _validate_embedding(np.array([], dtype=np.float32))


def test_validate_embedding_rejects_nan():
    from sauron.speakers.profiles import _validate_embedding
    emb = np.array([1.0, float("nan"), 0.5], dtype=np.float32)
    with pytest.raises(ValueError, match="NaN"):
        _validate_embedding(emb)


def test_validate_embedding_rejects_inf():
    from sauron.speakers.profiles import _validate_embedding
    emb = np.array([1.0, float("inf"), 0.5], dtype=np.float32)
    with pytest.raises(ValueError, match="Inf"):
        _validate_embedding(emb)


def test_validate_embedding_rejects_zero_norm():
    from sauron.speakers.profiles import _validate_embedding
    emb = np.zeros(10, dtype=np.float32)
    with pytest.raises(ValueError, match="Zero-norm"):
        _validate_embedding(emb)


def test_validate_embedding_rejects_abnormal_norm():
    from sauron.speakers.profiles import _validate_embedding
    emb = np.ones(10, dtype=np.float32) * 50  # norm ~158
    with pytest.raises(ValueError, match="Abnormal norm"):
        _validate_embedding(emb)


def test_validate_embedding_returns_float32():
    from sauron.speakers.profiles import _validate_embedding
    emb = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    result = _validate_embedding(emb)
    assert result.dtype == np.float32


# -- enroll_speaker --


def test_enroll_speaker_creates_profile(profile_db):
    from sauron.speakers.profiles import enroll_speaker

    emb = _random_embedding()
    profile_id = enroll_speaker(
        contact_id="contact_1",
        display_name="Alice Smith",
        embedding=emb,
        conversation_id=None,
    )

    assert profile_id is not None
    conn = sqlite3.connect(str(profile_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM voice_profiles WHERE id = ?", (profile_id,)).fetchone()
    conn.close()
    assert row is not None
    assert row["display_name"] == "Alice Smith"
    assert row["sample_count"] == 1
    assert row["confidence_score"] == 0.5


def test_enroll_speaker_creates_sample(profile_db):
    from sauron.speakers.profiles import enroll_speaker

    emb = _random_embedding()
    profile_id = enroll_speaker(
        contact_id="contact_1",
        display_name="Alice Smith",
        embedding=emb,
    )

    conn = sqlite3.connect(str(profile_db))
    conn.row_factory = sqlite3.Row
    samples = conn.execute(
        "SELECT * FROM voice_samples WHERE voice_profile_id = ?", (profile_id,)
    ).fetchall()
    conn.close()
    assert len(samples) == 1


def test_enroll_speaker_links_contact(profile_db):
    from sauron.speakers.profiles import enroll_speaker

    emb = _random_embedding()
    profile_id = enroll_speaker(
        contact_id="contact_1",
        display_name="Alice Smith",
        embedding=emb,
    )

    conn = sqlite3.connect(str(profile_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT voice_profile_id FROM unified_contacts WHERE id = ?", ("contact_1",)
    ).fetchone()
    conn.close()
    assert row["voice_profile_id"] == profile_id


# -- add_sample --


def test_add_sample_updates_mean_and_count(profile_db):
    from sauron.speakers.profiles import enroll_speaker, add_sample

    emb1 = _random_embedding()
    profile_id = enroll_speaker(
        contact_id="contact_1",
        display_name="Alice Smith",
        embedding=emb1,
    )

    emb2 = _random_embedding()
    add_sample(
        profile_id=profile_id,
        embedding=emb2,
        conversation_id="conv_2",
        source_type="auto",
        confirmation_method="calendar",
    )

    conn = sqlite3.connect(str(profile_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM voice_profiles WHERE id = ?", (profile_id,)).fetchone()
    conn.close()
    assert row["sample_count"] == 2
    # confidence = min(1.0, 2 * 0.15 + 0.25) = 0.55
    assert abs(row["confidence_score"] - 0.55) < 0.01


def test_add_sample_recalculates_mean_embedding(profile_db):
    from sauron.speakers.profiles import enroll_speaker, add_sample

    dim = 192
    emb1 = _random_embedding(dim)
    profile_id = enroll_speaker(
        contact_id="contact_1",
        display_name="Alice Smith",
        embedding=emb1,
    )

    emb2 = _random_embedding(dim)
    add_sample(
        profile_id=profile_id,
        embedding=emb2,
        conversation_id="conv_2",
        source_type="auto",
        confirmation_method="calendar",
    )

    conn = sqlite3.connect(str(profile_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT mean_embedding FROM voice_profiles WHERE id = ?", (profile_id,)).fetchone()
    conn.close()

    stored_mean = np.frombuffer(row["mean_embedding"], dtype=np.float32)
    expected_mean = np.mean([emb1, emb2], axis=0).astype(np.float32)
    # Validate after re-normalization by _validate_embedding
    np.testing.assert_allclose(stored_mean, expected_mean, atol=1e-5)


# -- get_profile --


def test_get_profile_returns_enrolled(profile_db):
    from sauron.speakers.profiles import enroll_speaker, get_profile

    emb = _random_embedding()
    profile_id = enroll_speaker(
        contact_id="contact_1",
        display_name="Alice Smith",
        embedding=emb,
    )

    profile = get_profile(profile_id)
    assert profile is not None
    assert profile["display_name"] == "Alice Smith"


def test_get_profile_returns_none_for_missing(profile_db):
    from sauron.speakers.profiles import get_profile
    assert get_profile("nonexistent") is None


# -- list_profiles --


def test_list_profiles_empty(profile_db):
    from sauron.speakers.profiles import list_profiles
    assert list_profiles() == []


def test_list_profiles_returns_enrolled(profile_db):
    from sauron.speakers.profiles import enroll_speaker, list_profiles

    emb = _random_embedding()
    enroll_speaker(
        contact_id="contact_1",
        display_name="Alice Smith",
        embedding=emb,
    )

    profiles = list_profiles()
    assert len(profiles) == 1
    assert profiles[0]["display_name"] == "Alice Smith"
