"""Test routing retry job — Audit Fix #2."""

import json
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from tests.helpers import seed_conversation


def _seed_failed_route(conn, conv_id, route_id, attempts=1, payload=None):
    """Helper: insert a failed routing_log entry."""
    conn.execute(
        """INSERT INTO routing_log (id, conversation_id, target_system, route_type,
           object_class, status, attempts, last_attempt_at, payload_json, created_at)
           VALUES (?, ?, 'networking', 'direct_write', 'conversation_bundle',
                   'failed', ?, datetime('now'), ?, datetime('now'))""",
        (route_id, conv_id, attempts, json.dumps(payload or {"test": True})),
    )
    conn.commit()


@patch("sauron.routing.networking.route_to_networking_app")
def test_retry_deduplicates_by_conversation_id(mock_route, test_conn, patch_get_connection):
    """3 rows for 2 conversations → only 2 route calls."""
    cid1 = seed_conversation(test_conn, conv_id="conv_dedup_1")
    cid2 = seed_conversation(test_conn, conv_id="conv_dedup_2")
    _seed_failed_route(test_conn, cid1, "rl_dd1")
    _seed_failed_route(test_conn, cid1, "rl_dd2")  # duplicate
    _seed_failed_route(test_conn, cid2, "rl_dd3")

    mock_route.return_value = True

    from sauron.routing.retry import retry_failed_routes_job
    retry_failed_routes_job()
    assert mock_route.call_count == 2


@patch("sauron.routing.networking.route_to_networking_app")
def test_retry_passes_is_retry_true(mock_route, test_conn, patch_get_connection):
    """retry_failed_routes_job passes is_retry=True."""
    cid = seed_conversation(test_conn, conv_id="conv_isretry")
    _seed_failed_route(test_conn, cid, "rl_ir1")
    mock_route.return_value = True

    from sauron.routing.retry import retry_failed_routes_job
    retry_failed_routes_job()
    _, kwargs = mock_route.call_args
    assert kwargs.get("is_retry") is True


@patch("sauron.routing.networking.route_to_networking_app")
def test_retry_success_updates_status_to_sent(mock_route, test_conn, patch_get_connection):
    """Successful retry updates routing_log status to 'sent'."""
    cid = seed_conversation(test_conn, conv_id="conv_sent")
    _seed_failed_route(test_conn, cid, "rl_sent1")
    mock_route.return_value = True

    from sauron.routing.retry import retry_failed_routes_job
    retry_failed_routes_job()

    row = test_conn.execute(
        "SELECT status FROM routing_log WHERE id = 'rl_sent1'"
    ).fetchone()
    assert row["status"] == "sent"


@patch("sauron.routing.networking.route_to_networking_app")
def test_retry_failure_bumps_attempts_only(mock_route, test_conn, patch_get_connection):
    """Failed retry increments attempts but keeps status='failed'."""
    cid = seed_conversation(test_conn, conv_id="conv_bump")
    _seed_failed_route(test_conn, cid, "rl_bump1", attempts=2)
    mock_route.return_value = False

    from sauron.routing.retry import retry_failed_routes_job
    retry_failed_routes_job()

    row = test_conn.execute(
        "SELECT status, attempts FROM routing_log WHERE id = 'rl_bump1'"
    ).fetchone()
    assert row["status"] == "failed"
    assert row["attempts"] == 3


@patch("sauron.routing.networking.route_to_networking_app")
def test_retry_does_not_create_new_log_entry(mock_route, test_conn, patch_get_connection):
    """Retry does not create additional routing_log entries."""
    cid = seed_conversation(test_conn, conv_id="conv_nodup")
    _seed_failed_route(test_conn, cid, "rl_nodup1")
    mock_route.return_value = False

    before = test_conn.execute("SELECT COUNT(*) FROM routing_log").fetchone()[0]

    from sauron.routing.retry import retry_failed_routes_job
    retry_failed_routes_job()

    after = test_conn.execute("SELECT COUNT(*) FROM routing_log").fetchone()[0]
    assert after == before


@patch("sauron.routing.networking.route_to_networking_app")
def test_retry_sets_routed_at_on_success(mock_route, test_conn, patch_get_connection):
    """Successful retry sets conversations.routed_at."""
    cid = seed_conversation(test_conn, conv_id="conv_routedat")
    _seed_failed_route(test_conn, cid, "rl_ra1")
    mock_route.return_value = True

    from sauron.routing.retry import retry_failed_routes_job
    retry_failed_routes_job()

    row = test_conn.execute(
        "SELECT routed_at FROM conversations WHERE id = ?", (cid,)
    ).fetchone()
    assert row["routed_at"] is not None


@patch("sauron.routing.networking.route_to_networking_app")
@patch("sauron.routing.retry.get_failed_routes")
def test_retry_skips_when_no_failed_routes(mock_get_failed, mock_route):
    """No calls when nothing is failed."""
    mock_get_failed.return_value = []
    from sauron.routing.retry import retry_failed_routes_job
    retry_failed_routes_job()
    mock_route.assert_not_called()
