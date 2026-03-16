"""Test routing_log CRUD + retry cap."""

import json
import pytest

from sauron.routing.routing_log import (
    log_route,
    log_routing_failure,
    log_routing_success,
    log_pending_entity,
    get_failed_routes,
    get_pending_routes_for_entity,
    MAX_RETRY_ATTEMPTS,
)
from tests.helpers import seed_conversation


def test_log_route_creates_entry(test_conn):
    """log_route creates a routing_log row with correct fields."""
    cid = seed_conversation(test_conn, conv_id="conv_1")
    log_id = log_route(
        conversation_id=cid,
        target_system="networking",
        object_class="interaction",
        status="sent",
        payload={"key": "value"},
        conn=test_conn,
    )
    test_conn.commit()
    row = test_conn.execute(
        "SELECT * FROM routing_log WHERE id = ?", (log_id,)
    ).fetchone()
    assert row is not None
    assert row["conversation_id"] == cid
    assert row["target_system"] == "networking"
    assert row["status"] == "sent"
    assert json.loads(row["payload_json"]) == {"key": "value"}


def test_log_routing_failure_sets_attempts_1(test_conn):
    """log_routing_failure creates entry with status=failed, attempts=1."""
    cid = seed_conversation(test_conn, conv_id="conv_fail")
    log_id = log_routing_failure(
        conversation_id=cid,
        object_class="conversation_bundle",
        payload={"test": True},
        error="Test error",
        conn=test_conn,
    )
    test_conn.commit()
    row = test_conn.execute(
        "SELECT status, attempts, last_error FROM routing_log WHERE id = ?", (log_id,)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["attempts"] == 1
    assert row["last_error"] == "Test error"


def test_log_routing_success_sets_status_sent(test_conn):
    """log_routing_success creates entry with status=sent."""
    cid = seed_conversation(test_conn, conv_id="conv_ok")
    log_id = log_routing_success(
        conversation_id=cid,
        object_class="interaction",
        payload={"ok": True},
        conn=test_conn,
    )
    test_conn.commit()
    row = test_conn.execute(
        "SELECT status FROM routing_log WHERE id = ?", (log_id,)
    ).fetchone()
    assert row["status"] == "sent"


def test_log_pending_entity_stores_payload(test_conn):
    """log_pending_entity creates entry with status=pending_entity and serialized payload."""
    cid = seed_conversation(test_conn, conv_id="conv_pending")
    payload = {"synthesis": {"summary": "test"}}
    log_id = log_pending_entity(
        conversation_id=cid,
        entity_id="entity_123",
        payload=payload,
        conn=test_conn,
    )
    test_conn.commit()
    row = test_conn.execute(
        "SELECT status, entity_id, payload_json FROM routing_log WHERE id = ?", (log_id,)
    ).fetchone()
    assert row["status"] == "pending_entity"
    assert row["entity_id"] == "entity_123"
    assert json.loads(row["payload_json"]) == payload


def test_get_failed_routes_respects_max_attempts(test_conn):
    """Routes with attempts >= MAX_RETRY_ATTEMPTS are not returned."""
    cid = seed_conversation(test_conn, conv_id="conv_maxed")
    test_conn.execute(
        """INSERT INTO routing_log (id, conversation_id, target_system, route_type,
           object_class, status, attempts, last_attempt_at, created_at)
           VALUES ('rl1', ?, 'networking', 'direct_write', 'conversation_bundle',
                   'failed', ?, datetime('now'), datetime('now'))""",
        (cid, MAX_RETRY_ATTEMPTS),
    )
    test_conn.commit()
    results = get_failed_routes(conn=test_conn)
    assert len(results) == 0


def test_get_failed_routes_returns_eligible(test_conn):
    """Routes with attempts < MAX_RETRY_ATTEMPTS are returned."""
    cid = seed_conversation(test_conn, conv_id="conv_retry")
    test_conn.execute(
        """INSERT INTO routing_log (id, conversation_id, target_system, route_type,
           object_class, status, attempts, last_attempt_at, created_at)
           VALUES ('rl2', ?, 'networking', 'direct_write', 'conversation_bundle',
                   'failed', 2, datetime('now'), datetime('now'))""",
        (cid,),
    )
    test_conn.commit()
    results = get_failed_routes(conn=test_conn)
    assert len(results) == 1
    assert results[0]["conversation_id"] == cid


def test_get_failed_routes_limit(test_conn):
    """get_failed_routes respects limit parameter."""
    for i in range(5):
        cid = seed_conversation(test_conn, conv_id=f"conv_lim_{i}")
        test_conn.execute(
            """INSERT INTO routing_log (id, conversation_id, target_system, route_type,
               object_class, status, attempts, last_attempt_at, created_at)
               VALUES (?, ?, 'networking', 'direct_write', 'conversation_bundle',
                       'failed', 1, datetime('now'), datetime('now'))""",
            (f"rl_lim_{i}", cid),
        )
    test_conn.commit()
    results = get_failed_routes(limit=2, conn=test_conn)
    assert len(results) == 2


def test_get_pending_routes_for_entity(test_conn):
    """get_pending_routes_for_entity filters by entity_id."""
    cid = seed_conversation(test_conn, conv_id="conv_pend_ent")
    test_conn.execute(
        """INSERT INTO routing_log (id, conversation_id, target_system, route_type,
           object_class, status, entity_id, attempts, payload_json, created_at)
           VALUES ('rl_pe1', ?, 'networking', 'direct_write', 'conversation_bundle',
                   'pending_entity', 'ent_A', 0, '{}', datetime('now'))""",
        (cid,),
    )
    test_conn.execute(
        """INSERT INTO routing_log (id, conversation_id, target_system, route_type,
           object_class, status, entity_id, attempts, payload_json, created_at)
           VALUES ('rl_pe2', ?, 'networking', 'direct_write', 'conversation_bundle',
                   'pending_entity', 'ent_B', 0, '{}', datetime('now'))""",
        (cid,),
    )
    test_conn.commit()
    results = get_pending_routes_for_entity("ent_A", conn=test_conn)
    assert len(results) == 1
    assert results[0]["entity_id"] == "ent_A"
