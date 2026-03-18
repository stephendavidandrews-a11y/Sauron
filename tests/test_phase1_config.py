"""Phase 1 verification tests — config portability.

Tests:
  - All config values have correct defaults (behaviour-preserving)
  - Env var overrides work for key values
  - No hardcoded paths remain outside config.py
"""
import importlib
import os
import re
from pathlib import Path

import pytest


SAURON_ROOT = Path("/Users/stephen/Documents/Website/Sauron")


class Test_ConfigDefaults:
    """Verify defaults match the original hardcoded production values."""

    def test_base_dir(self):
        from sauron.config import BASE_DIR
        assert BASE_DIR == Path("/Users/stephen/Documents/Website/Sauron")

    def test_db_path(self):
        from sauron.config import DB_PATH
        assert DB_PATH == Path("/Users/stephen/Documents/Website/Sauron/data/sauron.db")

    def test_archive_dir(self):
        from sauron.config import ARCHIVE_DIR
        assert ARCHIVE_DIR == Path("/Volumes/External/sauron/archive")

    def test_networking_app_url(self):
        from sauron.config import NETWORKING_APP_URL
        assert NETWORKING_APP_URL == "http://localhost:3000"

    def test_sauron_port(self):
        from sauron.config import SAURON_PORT
        assert SAURON_PORT == 8003
        assert isinstance(SAURON_PORT, int)

    def test_whisper_model(self):
        from sauron.config import WHISPER_MODEL
        assert WHISPER_MODEL == "medium.en"

    def test_triage_model(self):
        from sauron.config import TRIAGE_MODEL
        assert TRIAGE_MODEL == "claude-haiku-4-5-20251001"

    def test_extraction_model(self):
        from sauron.config import EXTRACTION_MODEL
        assert EXTRACTION_MODEL == "claude-sonnet-4-6"

    def test_claims_model(self):
        from sauron.config import CLAIMS_MODEL
        assert CLAIMS_MODEL == "claude-sonnet-4-6"

    def test_embedding_model(self):
        from sauron.config import EMBEDDING_MODEL
        assert EMBEDDING_MODEL == "sentence-transformers/all-MiniLM-L6-v2"

    def test_embedding_dim(self):
        from sauron.config import EMBEDDING_DIM
        assert EMBEDDING_DIM == 384
        assert isinstance(EMBEDDING_DIM, int)

    def test_morning_email_recipient(self):
        from sauron.config import MORNING_EMAIL_RECIPIENT
        assert MORNING_EMAIL_RECIPIENT == "stephen@stephenandrews.org"

    def test_google_calendar_id(self):
        from sauron.config import GOOGLE_CALENDAR_ID
        assert GOOGLE_CALENDAR_ID == "stephen@stephenandrews.org"

    def test_inbox_subdirs(self):
        from sauron.config import INBOX_PI, INBOX_PLAUD, INBOX_IPHONE_DIR, INBOX_EMAIL_DIR
        assert INBOX_PI.name == "pi"
        assert INBOX_PLAUD.name == "plaud"
        assert INBOX_IPHONE_DIR.name == "iphone"
        assert INBOX_EMAIL_DIR.name == "email"

    def test_numeric_defaults(self):
        from sauron.config import (
            BASELINE_EMA_ALPHA, DEVIATION_SIGNIFICANT, DEVIATION_MODERATE,
            SILENCE_BOUNDARY_SECONDS, MAX_RECORDING_SECONDS,
            HOT_RETENTION_DAYS,
        )
        assert BASELINE_EMA_ALPHA == pytest.approx(0.1)
        assert DEVIATION_SIGNIFICANT == pytest.approx(0.50)
        assert DEVIATION_MODERATE == pytest.approx(0.20)
        assert SILENCE_BOUNDARY_SECONDS == 180
        assert MAX_RECORDING_SECONDS == 7200
        assert HOT_RETENTION_DAYS == 30

    def test_supported_formats_unchanged(self):
        from sauron.config import SUPPORTED_FORMATS
        assert SUPPORTED_FORMATS == {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}


class Test_EnvOverrides:
    """Verify env vars override config values when set."""

    def test_base_dir_override(self, monkeypatch):
        monkeypatch.setenv("SAURON_BASE_DIR", "/tmp/test-sauron")
        import sauron.config
        importlib.reload(sauron.config)
        try:
            assert sauron.config.BASE_DIR == Path("/tmp/test-sauron")
        finally:
            monkeypatch.delenv("SAURON_BASE_DIR")
            importlib.reload(sauron.config)

    def test_db_path_override(self, monkeypatch):
        monkeypatch.setenv("SAURON_DB_PATH", "/tmp/test.db")
        import sauron.config
        importlib.reload(sauron.config)
        try:
            assert sauron.config.DB_PATH == Path("/tmp/test.db")
        finally:
            monkeypatch.delenv("SAURON_DB_PATH")
            importlib.reload(sauron.config)

    def test_port_override_is_int(self, monkeypatch):
        monkeypatch.setenv("SAURON_PORT", "9999")
        import sauron.config
        importlib.reload(sauron.config)
        try:
            assert sauron.config.SAURON_PORT == 9999
            assert isinstance(sauron.config.SAURON_PORT, int)
        finally:
            monkeypatch.delenv("SAURON_PORT")
            importlib.reload(sauron.config)

    def test_networking_app_url_override(self, monkeypatch):
        monkeypatch.setenv("NETWORKING_APP_URL", "http://staging:4000")
        import sauron.config
        importlib.reload(sauron.config)
        try:
            assert sauron.config.NETWORKING_APP_URL == "http://staging:4000"
        finally:
            monkeypatch.delenv("NETWORKING_APP_URL")
            importlib.reload(sauron.config)


class Test_NoHardcodedPaths:
    """Verify no other files hardcode the Mac Mini path."""

    def _python_files(self):
        """Yield all .py files under sauron/ excluding config.py and __pycache__."""
        sauron_dir = SAURON_ROOT / "sauron"
        for p in sauron_dir.rglob("*.py"):
            if "__pycache__" in str(p):
                continue
            if p.name == "config.py":
                continue
            yield p

    def test_no_hardcoded_base_dir(self):
        """No Python file outside config.py should hardcode the base path."""
        violations = []
        for p in self._python_files():
            content = p.read_text()
            # Look for the literal hardcoded path (not imports from config)
            if "/Users/stephen/Documents/Website/Sauron" in content:
                # Exclude comments and docstrings that might reference it
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if "/Users/stephen/Documents/Website/Sauron" in stripped:
                        if not stripped.startswith("#") and not stripped.startswith('"""'):
                            violations.append(f"{p.relative_to(SAURON_ROOT)}:{i}")
        assert violations == [], \
            f"Hardcoded base path found in: {violations}"
