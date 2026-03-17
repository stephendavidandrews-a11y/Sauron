"""Database connection management for sauron.db."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sauron.config import DB_PATH


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Get a SQLite connection with row_factory and WAL mode."""
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")  # 30s retry on lock instead of immediate fail
    return conn


@contextmanager
def get_db(db_path: Path = DB_PATH):
    """Context manager that yields a connection and auto-closes on exit.

    Usage:
        with get_db() as conn:
            conn.execute(...)
            conn.commit()
    """
    conn = get_connection(db_path)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
