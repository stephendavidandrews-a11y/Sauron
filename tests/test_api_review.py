"""Test review lifecycle endpoints — critical path."""

import uuid
from unittest.mock import patch, MagicMock

import pytest
from tests.helpers import seed_conversation


@patch("sauron.routing.router.route_extraction")
@patch("sauron.routing.reviewed_payload.build_reviewed_payload")
def test_mark_reviewed_sets_status_completed(mock_build, mock_route, app_client, patch_get_connection):
    """mark_reviewed sets processing_status=completed and reviewed_at."""
    conn = patch_get_connection()
    cid = seed_conversation(conn, conv_id="conv_rev1", status="awaiting_claim_review")
    conn.close()

    mock_build.return_value = {"synthesis": {"summary": "test"}}

    resp = app_client.post(f"/api/conversations/{cid}/review")
    assert resp.status_code == 200

    conn = patch_get_connection()
    row = conn.execute(
        "SELECT processing_status, reviewed_at FROM conversations WHERE id = ?", (cid,)
    ).fetchone()
    conn.close()
    assert row["processing_status"] == "completed"
    assert row["reviewed_at"] is not None


@patch("sauron.routing.router.route_extraction")
@patch("sauron.routing.reviewed_payload.build_reviewed_payload")
def test_mark_reviewed_returns_stats(mock_build, mock_route, app_client, patch_get_connection):
    """mark_reviewed returns stats dict in response."""
    conn = patch_get_connection()
    cid = seed_conversation(conn, conv_id="conv_rev2", status="awaiting_claim_review")
    conn.close()

    mock_build.return_value = {"synthesis": {"summary": "test"}}

    resp = app_client.post(f"/api/conversations/{cid}/review")
    data = resp.json()
    assert data["status"] == "ok"
    assert data["reviewed"] is True
    # Stats may be None or dict depending on whether tables have data
    if data["stats"] is not None:
        assert "approved" in data["stats"]
        assert "dismissed" in data["stats"]


@patch("sauron.routing.router.route_extraction")
@patch("sauron.routing.reviewed_payload.build_reviewed_payload")
def test_mark_reviewed_triggers_routing(mock_build, mock_route, app_client, patch_get_connection):
    """mark_reviewed calls route_extraction."""
    conn = patch_get_connection()
    cid = seed_conversation(conn, conv_id="conv_rev3", status="awaiting_claim_review")
    conn.close()

    mock_build.return_value = {"synthesis": {"summary": "test"}}

    app_client.post(f"/api/conversations/{cid}/review")
    mock_route.assert_called_once()
    call_args = mock_route.call_args[0]
    assert call_args[0] == cid


def test_mark_reviewed_404_nonexistent(app_client):
    """404 for nonexistent conversation."""
    resp = app_client.post("/api/conversations/nonexistent-id/review")
    assert resp.status_code == 404


@patch("sauron.routing.router.route_extraction")
@patch("sauron.routing.reviewed_payload.build_reviewed_payload")
def test_mark_reviewed_sets_routed_at(mock_build, mock_route, app_client, patch_get_connection):
    """routed_at is populated when routing succeeds (no pending/failed entries)."""
    conn = patch_get_connection()
    cid = seed_conversation(conn, conv_id="conv_rev5", status="awaiting_claim_review")
    conn.close()

    mock_build.return_value = {"synthesis": {"summary": "test"}}

    resp = app_client.post(f"/api/conversations/{cid}/review")
    assert resp.status_code == 200

    conn = patch_get_connection()
    row = conn.execute(
        "SELECT routed_at FROM conversations WHERE id = ?", (cid,)
    ).fetchone()
    conn.close()
    assert row["routed_at"] is not None


@patch("sauron.routing.router.route_extraction")
@patch("sauron.routing.reviewed_payload.build_reviewed_payload")
def test_mark_reviewed_no_routed_at_on_failure(mock_build, mock_route, app_client, patch_get_connection):
    """routed_at stays NULL when routing fails."""
    conn = patch_get_connection()
    cid = seed_conversation(conn, conv_id="conv_rev6", status="awaiting_claim_review")
    # Pre-insert a failed routing_log entry to simulate routing failure
    conn.execute(
        """INSERT INTO routing_log (id, conversation_id, target_system, route_type,
           object_class, status, attempts, created_at)
           VALUES ('rl_rev6', ?, 'networking', 'direct_write', 'conversation_bundle',
                   'failed', 1, datetime('now'))""",
        (cid,),
    )
    conn.commit()
    conn.close()

    mock_build.return_value = {"synthesis": {"summary": "test"}}

    resp = app_client.post(f"/api/conversations/{cid}/review")
    assert resp.status_code == 200

    conn = patch_get_connection()
    row = conn.execute(
        "SELECT routed_at FROM conversations WHERE id = ?", (cid,)
    ).fetchone()
    conn.close()
    assert row["routed_at"] is None


def test_discard_from_allowed_status(app_client, patch_get_connection):
    """Discard from awaiting_claim_review → status=discarded."""
    conn = patch_get_connection()
    cid = seed_conversation(conn, conv_id="conv_disc1", status="awaiting_claim_review")
    conn.close()

    resp = app_client.patch(
        f"/api/conversations/{cid}/discard",
        json={"reason": "test_discard"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["discarded"] is True

    conn = patch_get_connection()
    row = conn.execute(
        "SELECT processing_status FROM conversations WHERE id = ?", (cid,)
    ).fetchone()
    conn.close()
    assert row["processing_status"] == "discarded"
