"""Phase 2 verification tests -- concurrency discipline.

Tests:
  - No raw Thread(daemon=True) launches remain in production code
  - Shared executor module works correctly
  - Pool stats endpoint returns expected structure
"""
import threading
import time
from pathlib import Path

import pytest


SAURON_ROOT = Path("/Users/stephen/Documents/Website/Sauron")


class Test_NoRawThreads:
    """Verify no production code uses raw Thread(daemon=True)."""

    def _python_files(self):
        sauron_dir = SAURON_ROOT / "sauron"
        for p in sauron_dir.rglob("*.py"):
            if "__pycache__" in str(p) or p.name == "executor.py":
                continue
            yield p

    def test_no_daemon_thread_launches(self):
        violations = []
        for p in self._python_files():
            content = p.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "daemon=True" in stripped and "Thread" in stripped:
                    violations.append(f"{p.relative_to(SAURON_ROOT)}:{i}")
        assert violations == [], \
            f"Raw daemon Thread launches found: {violations}"


class Test_ExecutorModule:
    """Verify the shared executor module works."""

    def test_submit_pipeline_job_returns_future(self):
        from sauron.executor import submit_pipeline_job, shutdown
        try:
            future = submit_pipeline_job(lambda: 42)
            assert future.result(timeout=5) == 42
        finally:
            shutdown(wait=True)

    def test_submit_background_job_returns_future(self):
        from sauron.executor import submit_background_job, shutdown
        try:
            future = submit_background_job(lambda: "ok")
            assert future.result(timeout=5) == "ok"
        finally:
            shutdown(wait=True)

    def test_pool_stats_structure(self):
        from sauron.executor import pool_stats, shutdown
        try:
            stats = pool_stats()
            assert "pipeline" in stats
            assert "background" in stats
            assert "max_workers" in stats["pipeline"]
            assert stats["pipeline"]["max_workers"] == 2
            assert stats["background"]["max_workers"] == 3
        finally:
            shutdown(wait=True)

    def test_pipeline_pool_limits_concurrency(self):
        from sauron.executor import submit_pipeline_job, shutdown

        active = {"count": 0, "max_seen": 0}
        lock = threading.Lock()

        def slow_job():
            with lock:
                active["count"] += 1
                active["max_seen"] = max(active["max_seen"], active["count"])
            time.sleep(0.2)
            with lock:
                active["count"] -= 1

        try:
            futures = [submit_pipeline_job(slow_job) for _ in range(5)]
            for f in futures:
                f.result(timeout=10)
            assert active["max_seen"] <= 2, \
                f"Pipeline pool ran {active['max_seen']} concurrently (max 2)"
        finally:
            shutdown(wait=True)

    def test_shutdown_and_recreate(self):
        from sauron.executor import submit_pipeline_job, shutdown
        try:
            f1 = submit_pipeline_job(lambda: 1)
            assert f1.result(timeout=5) == 1
            shutdown(wait=True)
            f2 = submit_pipeline_job(lambda: 2)
            assert f2.result(timeout=5) == 2
        finally:
            shutdown(wait=True)


class Test_MainUsesExecutor:
    """Verify main.py uses the shared executor, not its own."""

    def test_no_threadpoolexecutor_in_main(self):
        main_path = SAURON_ROOT / "sauron" / "main.py"
        content = main_path.read_text()
        assert "ThreadPoolExecutor" not in content

    def test_main_imports_executor(self):
        main_path = SAURON_ROOT / "sauron" / "main.py"
        content = main_path.read_text()
        assert "from sauron.executor import" in content
