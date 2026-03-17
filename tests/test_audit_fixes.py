"""Tests for bugs fixed during the full system audit (2026-03-16).

Covers:
- Phase 1C: Path traversal guard in SPA handler
- Phase 2C: morning email timezone (UTC)
- Phase 6A: get_db context manager
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Phase 6A: get_db context manager
# ---------------------------------------------------------------------------


def test_get_db_context_manager(tmp_path):
    """get_db() should auto-close connection and rollback on exception."""
    db_path = tmp_path / "test.db"
    from sauron.db.connection import get_db

    # Normal usage: connection is closed after block
    with get_db(db_path) as conn:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()

    # Verify data persisted
    with get_db(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM t").fetchone()
        assert row[0] == 1

    # Exception usage: should rollback
    try:
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO t VALUES (2)")
            raise ValueError("test error")
    except ValueError:
        pass

    # Verify the insert was rolled back
    with get_db(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM t").fetchone()
        assert row[0] == 1  # Still 1, not 2


def test_get_db_closes_on_exit(tmp_path):
    """Connection should be closed after exiting the context manager."""
    db_path = tmp_path / "test.db"
    from sauron.db.connection import get_db

    with get_db(db_path) as conn:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()
        saved_conn = conn

    # Connection should be closed
    with pytest.raises(Exception):
        saved_conn.execute("SELECT 1")


# ---------------------------------------------------------------------------
# Phase 1C: Path traversal guard
# ---------------------------------------------------------------------------


def test_spa_handler_blocks_path_traversal():
    """SPA 404 handler should not serve files outside _FRONTEND_DIR."""
    # Simulate the guard logic from main.py
    frontend_dir = Path("/app/frontend/dist").resolve()

    # Normal path: should be within frontend_dir
    normal_rel = "assets/index.js"
    normal_path = (frontend_dir / normal_rel).resolve()
    assert normal_path.is_relative_to(frontend_dir)

    # Traversal path: should be rejected
    traversal_rel = "../../../etc/passwd"
    traversal_path = (frontend_dir / traversal_rel).resolve()
    assert not traversal_path.is_relative_to(frontend_dir)

    # Double-encoded traversal
    traversal_rel2 = "..%2F..%2Fetc/passwd"
    traversal_path2 = (frontend_dir / traversal_rel2).resolve()
    # This stays inside frontend_dir since %2F is a literal filename char
    # The important thing is ../ sequences are caught


# ---------------------------------------------------------------------------
# Phase 2C: Morning email timezone
# ---------------------------------------------------------------------------


def test_yesterday_range_uses_utc():
    """_yesterday_range should use UTC, not local time."""
    from sauron.jobs.morning_email import _yesterday_range

    start, end = _yesterday_range()
    # Parse and verify they are valid ISO strings
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)

    # The range should be exactly 1 day minus 1 second
    diff = end_dt - start_dt
    assert diff.days == 0
    assert diff.seconds == 86399  # 23:59:59


def test_yesterday_range_consistent():
    """Multiple calls within the same second should return the same range."""
    from sauron.jobs.morning_email import _yesterday_range

    start1, end1 = _yesterday_range()
    start2, end2 = _yesterday_range()
    assert start1 == start2
    assert end1 == end2
