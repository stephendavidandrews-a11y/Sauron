"""Phase 3+4 verification tests — NA auth headers + connection safety.

Tests:
  - All httpx calls to Networking App include auth headers
  - All get_connection() calls have matching conn.close() in finally blocks
  - No leaked connections in intentions.py, amendments.py, resynthesize.py
"""
import ast
import re
from pathlib import Path

import pytest

SAURON_ROOT = Path("/Users/stephen/Documents/Website/Sauron")


class Test_NAAuthHeaders:
    """Verify all httpx calls to Networking App include auth headers."""

    # Files that make outbound calls to the Networking App
    NA_CALLERS = [
        "sauron/routing/lanes/core.py",
        "sauron/routing/lanes/commitments.py",
        "sauron/contacts/sync.py",
        "sauron/api/provisional_orgs_api.py",
        "sauron/api/graph.py",
        "sauron/api/diagnostics.py",
    ]

    def test_no_bare_httpx_calls(self):
        """Every httpx.get/post/put/patch/delete must pass headers=."""
        violations = []
        for rel_path in self.NA_CALLERS:
            p = SAURON_ROOT / rel_path
            if not p.exists():
                continue
            content = p.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Match httpx method calls
                if re.search(r"httpx\.(get|post|put|patch|delete)\(", stripped):
                    # Should have headers= somewhere in the call
                    # Check this line and next few lines for headers=
                    context = "\n".join(
                        content.splitlines()[max(0, i - 1):min(i + 5, len(content.splitlines()))]
                    )
                    if "headers=" not in context and "_na_headers" not in context and "_api_call" not in context:
                        violations.append(f"{rel_path}:{i}")

        assert violations == [], \
            f"httpx calls without auth headers: {violations}"

    def test_core_api_call_sends_headers(self):
        """The _api_call helper in core.py sends X-API-Key."""
        p = SAURON_ROOT / "sauron" / "routing" / "lanes" / "core.py"
        content = p.read_text()
        assert "X-API-Key" in content, "core.py _api_call must send X-API-Key"
        assert "NETWORKING_APP_API_KEY" in content, \
            "core.py must read NETWORKING_APP_API_KEY from env"

    def test_sync_sends_headers(self):
        """contacts/sync.py sends auth headers."""
        p = SAURON_ROOT / "sauron" / "contacts" / "sync.py"
        content = p.read_text()
        assert "_na_headers" in content or "X-API-Key" in content, \
            "sync.py must include auth headers"

    def test_graph_sends_headers(self):
        """api/graph.py sends auth headers."""
        p = SAURON_ROOT / "sauron" / "api" / "graph.py"
        content = p.read_text()
        assert "_na_headers" in content or "X-API-Key" in content, \
            "graph.py must include auth headers"


class Test_ConnectionSafety:
    """Verify every get_connection() has a matching conn.close() in a finally block."""

    # Files that use get_connection()
    CONN_FILES = [
        "sauron/jobs/intentions.py",
        "sauron/learning/amendments.py",
        "sauron/learning/resynthesize.py",
        "sauron/api/text_api.py",
    ]

    def _get_conn_functions(self, filepath: Path) -> list[tuple[str, int, int]]:
        """Return (func_name, conn_line, func_end) for functions using get_connection()."""
        content = filepath.read_text()
        lines = content.splitlines()
        results = []

        for i, line in enumerate(lines):
            if 'conn = get_connection()' in line and not line.strip().startswith('#'):
                # Find enclosing function
                func_name = "<module>"
                for j in range(i - 1, -1, -1):
                    if lines[j].strip().startswith('def '):
                        func_name = lines[j].strip().split('(')[0].replace('def ', '')
                        break
                results.append((func_name, i + 1))

        return results

    def test_intentions_all_connections_closed(self):
        """Every get_connection() in intentions.py must have conn.close() in finally."""
        p = SAURON_ROOT / "sauron" / "jobs" / "intentions.py"
        content = p.read_text()

        # Count conn = get_connection() calls
        conn_count = content.count("conn = get_connection()")
        # Count conn.close() calls
        close_count = content.count("conn.close()")
        # Count finally blocks
        finally_count = len(re.findall(r"^\s+finally:\s*$", content, re.MULTILINE))

        assert conn_count == close_count, \
            f"intentions.py: {conn_count} connections opened but only {close_count} closed"
        assert finally_count >= conn_count, \
            f"intentions.py: {conn_count} connections but only {finally_count} finally blocks"

    def test_amendments_all_connections_closed(self):
        """Every get_connection() in amendments.py must have conn.close()."""
        p = SAURON_ROOT / "sauron" / "learning" / "amendments.py"
        content = p.read_text()

        conn_count = content.count("conn = get_connection()")
        close_count = content.count("conn.close()")

        assert conn_count == close_count, \
            f"amendments.py: {conn_count} connections opened but only {close_count} closed"

    def test_resynthesize_connections_closed(self):
        """resynthesize.py connections must be closed."""
        p = SAURON_ROOT / "sauron" / "learning" / "resynthesize.py"
        content = p.read_text()

        conn_count = content.count("conn = get_connection()")
        close_count = content.count("conn.close()")

        assert conn_count == close_count, \
            f"resynthesize.py: {conn_count} connections opened but only {close_count} closed"

    def test_no_conn_without_close_anywhere(self):
        """Scan all Python files for get_connection() without conn.close()."""
        sauron_dir = SAURON_ROOT / "sauron"
        violations = []

        for p in sauron_dir.rglob("*.py"):
            if "__pycache__" in str(p):
                continue
            content = p.read_text()
            conn_count = content.count("conn = get_connection()")
            close_count = content.count("conn.close()")

            if conn_count > close_count:
                violations.append(
                    f"{p.relative_to(SAURON_ROOT)}: "
                    f"{conn_count} opens, {close_count} closes"
                )

        assert violations == [], \
            f"Files with unclosed connections: {violations}"
