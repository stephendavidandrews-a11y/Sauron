"""Test DB connection pragmas — Audit Fix #1."""

import sqlite3
import pytest
from sauron.db.connection import get_connection


def test_wal_mode_enabled(tmp_path):
    """get_connection sets journal_mode to WAL."""
    db = tmp_path / "test.db"
    conn = get_connection(db)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_foreign_keys_enabled(tmp_path):
    """get_connection enables foreign_keys."""
    db = tmp_path / "test.db"
    conn = get_connection(db)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.close()
    assert fk == 1


def test_busy_timeout_set(tmp_path):
    """get_connection sets busy_timeout to 30000ms."""
    db = tmp_path / "test.db"
    conn = get_connection(db)
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    conn.close()
    assert timeout == 30000


def test_row_factory_is_row(tmp_path):
    """get_connection sets row_factory to sqlite3.Row."""
    db = tmp_path / "test.db"
    conn = get_connection(db)
    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_fk_enforcement_rejects_bad_ref(tmp_path):
    """Foreign key violations raise IntegrityError."""
    db = tmp_path / "test.db"
    conn = get_connection(db)
    conn.execute("CREATE TABLE parent (id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE child (id TEXT PRIMARY KEY, parent_id TEXT REFERENCES parent(id))"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO child (id, parent_id) VALUES ('c1', 'nonexistent')")
    conn.close()
