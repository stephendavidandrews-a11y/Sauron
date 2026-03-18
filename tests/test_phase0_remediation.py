"""Phase 0 verification tests for Sauron remediation.

Tests:
  0A — SQL injection whitelist on update_contact_preference
  0B — _SLOW_THRESHOLD is 5 (not 3)
  0C — Version consistency across pyproject.toml, __init__.py, main.py
  0D — ThreadPoolExecutor in claims.py is bounded
  0E — commitments.py uses _api_call, not direct httpx
"""
import importlib
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# 0A: SQL injection whitelist
# ---------------------------------------------------------------------------

class Test0A_SQLInjectionWhitelist:
    """Verify update_contact_preference rejects invalid field names."""

    def test_rejects_injection_attempt(self, tmp_path):
        """Passing a SQL-injection field name must raise ValueError."""
        from sauron.learning.amendments import update_contact_preference
        with pytest.raises(ValueError, match="Invalid preference field"):
            update_contact_preference("fake-id", "custom_notes; DROP TABLE users--", 1)

    def test_rejects_unknown_column(self, tmp_path):
        """Even innocuous but unlisted column names are rejected."""
        from sauron.learning.amendments import update_contact_preference
        with pytest.raises(ValueError, match="Invalid preference field"):
            update_contact_preference("fake-id", "nonexistent_column", "val")

    def test_allows_all_valid_fields(self):
        """Each whitelisted field should pass the guard (may fail on DB, that's fine)."""
        from sauron.learning.amendments import _ALLOWED_PREF_FIELDS, update_contact_preference
        for field in _ALLOWED_PREF_FIELDS:
            # We expect it to get past the whitelist check and fail on DB instead
            try:
                update_contact_preference("fake-contact-id", field, "test")
            except ValueError:
                pytest.fail(f"Valid field {field!r} was rejected by whitelist")
            except Exception:
                pass  # DB errors are expected — we just care the whitelist passed

    def test_whitelist_has_six_fields(self):
        """Whitelist should match the Pydantic model's 6 fields exactly."""
        from sauron.learning.amendments import _ALLOWED_PREF_FIELDS
        expected = {
            "commitment_confidence_threshold", "typical_follow_through_rate",
            "extraction_depth", "vocal_alert_sensitivity",
            "relationship_importance", "custom_notes",
        }
        assert _ALLOWED_PREF_FIELDS == expected


# ---------------------------------------------------------------------------
# 0B: _SLOW_THRESHOLD
# ---------------------------------------------------------------------------

class Test0B_SlowThreshold:
    """Verify the fast/slow threshold distinction is meaningful."""

    def test_slow_threshold_is_five(self):
        from sauron.learning.amendments import _SLOW_THRESHOLD
        assert _SLOW_THRESHOLD == 5, f"Expected 5, got {_SLOW_THRESHOLD}"

    def test_fast_threshold_is_three(self):
        from sauron.learning.amendments import _FAST_THRESHOLD
        assert _FAST_THRESHOLD == 3, f"Expected 3, got {_FAST_THRESHOLD}"

    def test_thresholds_differ(self):
        from sauron.learning.amendments import _FAST_THRESHOLD, _SLOW_THRESHOLD
        assert _FAST_THRESHOLD != _SLOW_THRESHOLD, \
            "Fast and slow thresholds must differ to provide behavioral distinction"

    def test_slow_higher_than_fast(self):
        from sauron.learning.amendments import _FAST_THRESHOLD, _SLOW_THRESHOLD
        assert _SLOW_THRESHOLD > _FAST_THRESHOLD, \
            "Slow types need MORE evidence before generalizing"


# ---------------------------------------------------------------------------
# 0C: Version consistency
# ---------------------------------------------------------------------------

class Test0C_VersionConsistency:
    """Verify all version strings agree."""

    def test_init_version_matches_pyproject(self):
        import sauron
        # Read pyproject.toml version
        pyproject = Path("/Users/stephen/Documents/Website/Sauron/pyproject.toml")
        content = pyproject.read_text()
        match = re.search(r'version\s*=\s*"([^"]+)"', content)
        assert match, "Could not find version in pyproject.toml"
        pyproject_version = match.group(1)
        assert sauron.__version__ == pyproject_version, \
            f"__init__.py ({sauron.__version__}) != pyproject.toml ({pyproject_version})"

    def test_main_docstring_matches(self):
        main_path = Path("/Users/stephen/Documents/Website/Sauron/sauron/main.py")
        content = main_path.read_text()
        pyproject = Path("/Users/stephen/Documents/Website/Sauron/pyproject.toml")
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject.read_text())
        version = match.group(1)
        assert f"v{version}" in content, \
            f"main.py docstring does not contain v{version}"


# ---------------------------------------------------------------------------
# 0D: Bounded ThreadPoolExecutor
# ---------------------------------------------------------------------------

class Test0D_BoundedExecutor:
    """Verify claims.py ThreadPoolExecutor is bounded."""

    def test_executor_has_max_workers(self):
        claims_path = Path("/Users/stephen/Documents/Website/Sauron/sauron/extraction/claims.py")
        content = claims_path.read_text()
        # Should NOT contain unbounded ThreadPoolExecutor()
        assert "ThreadPoolExecutor()" not in content, \
            "claims.py still has unbounded ThreadPoolExecutor()"
        # Should contain bounded version
        assert "ThreadPoolExecutor(max_workers=1)" in content, \
            "claims.py should have ThreadPoolExecutor(max_workers=1)"


# ---------------------------------------------------------------------------
# 0E: commitments.py uses _api_call
# ---------------------------------------------------------------------------

class Test0E_CommitmentsApiCall:
    """Verify commitments.py no longer makes direct httpx calls."""

    def test_no_direct_httpx_get(self):
        commitments_path = Path(
            "/Users/stephen/Documents/Website/Sauron/sauron/routing/lanes/commitments.py"
        )
        content = commitments_path.read_text()
        # Should not contain direct httpx.get calls
        assert "httpx.get(" not in content, \
            "commitments.py still has direct httpx.get() — should use _api_call"

    def test_uses_api_call_for_contact_get(self):
        commitments_path = Path(
            "/Users/stephen/Documents/Website/Sauron/sauron/routing/lanes/commitments.py"
        )
        content = commitments_path.read_text()
        assert '_api_call("GET"' in content, \
            "commitments.py should use _api_call for GET requests"
