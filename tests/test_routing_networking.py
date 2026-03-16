"""Test routing networking — Audit Fixes #3, #4."""

import json
import re
import uuid
from unittest.mock import patch, MagicMock

import pytest

from tests.helpers import seed_conversation, seed_contact


def _uuid():
    return str(uuid.uuid4())


def _make_extraction(summary="Test meeting", graph_edges=None):
    """Build a minimal extraction dict for routing tests."""
    return {
        "synthesis": {
            "summary": summary,
            "topics_discussed": ["test"],
            "graph_edges": graph_edges or [],
        },
        "claims": {},
    }


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
@patch("sauron.routing.networking.resolve_networking_contact_id")
def test_interaction_skipped_when_no_contact_id(mock_resolve, mock_api, mock_store,
                                                 test_conn, patch_get_connection):
    """No contactId → interaction not POSTed."""
    mock_resolve.return_value = None
    mock_api.return_value = (True, None, {"id": "int-1"})

    cid = seed_conversation(test_conn, conv_id="conv_no_cid")
    extraction = _make_extraction()

    from sauron.routing.networking import route_to_networking_app
    route_to_networking_app(cid, extraction)

    for call in mock_api.call_args_list:
        args = call[0]
        if len(args) > 1:
            assert "/api/interactions" not in str(args[1]), \
                "Interaction should be skipped when no contactId"


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
def test_interaction_sent_when_contact_id_provided(mock_api, mock_store,
                                                    test_conn, patch_get_connection):
    """contactId provided → interaction POSTed with contactId in payload."""
    na_id = _uuid()
    mock_api.return_value = (True, None, {"id": "int-2"})

    cid = seed_conversation(test_conn, conv_id="conv_with_cid")
    extraction = _make_extraction()

    from sauron.routing.networking import route_to_networking_app
    route_to_networking_app(cid, extraction, networking_app_contact_id=na_id)

    interaction_calls = [
        c for c in mock_api.call_args_list
        if len(c[0]) > 1 and "/api/interactions" in str(c[0][1])
    ]
    assert len(interaction_calls) >= 1, "Interaction POST should have been called"
    payload = interaction_calls[0][0][2]
    assert payload["contactId"] == na_id


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
def test_graph_edge_skipped_for_non_uuid_ids(mock_api, mock_store,
                                              test_conn, patch_get_connection):
    """Non-UUID contact IDs (like seed-treasury) → graph edge skipped."""
    na_id_valid = _uuid()
    eid1 = seed_contact(test_conn, name="Person A", networking_app_contact_id=na_id_valid)
    eid2 = seed_contact(test_conn, name="US Treasury", networking_app_contact_id="seed-treasury")

    # Add synthesis_entity_links for resolution
    test_conn.execute(
        """INSERT INTO synthesis_entity_links (id, conversation_id, object_type, object_index,
           field_name, original_name, resolved_entity_id, resolution_method, confidence, created_at)
           VALUES (?, 'conv_edge1', 'graph_edge', 0, 'from_entity', 'Person A', ?, 'exact', 1.0, datetime('now'))""",
        (_uuid(), eid1),
    )
    test_conn.execute(
        """INSERT INTO synthesis_entity_links (id, conversation_id, object_type, object_index,
           field_name, original_name, resolved_entity_id, resolution_method, confidence, created_at)
           VALUES (?, 'conv_edge1', 'graph_edge', 0, 'to_entity', 'US Treasury', ?, 'exact', 1.0, datetime('now'))""",
        (_uuid(), eid2),
    )
    test_conn.commit()

    cid = seed_conversation(test_conn, conv_id="conv_edge1")
    edges = [{"from_entity": "Person A", "to_entity": "US Treasury", "edge_type": "works_at", "strength": 0.8}]
    extraction = _make_extraction(graph_edges=edges)
    mock_api.return_value = (True, None, {"id": "int-3"})

    from sauron.routing.networking import route_to_networking_app
    route_to_networking_app(cid, extraction, networking_app_contact_id=_uuid())

    rel_calls = [
        c for c in mock_api.call_args_list
        if len(c[0]) > 1 and "/api/contact-relationships" in str(c[0][1])
    ]
    assert len(rel_calls) == 0, "Non-UUID IDs should not be sent to contact-relationships"


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
def test_graph_edge_sent_for_valid_uuid_ids(mock_api, mock_store,
                                             test_conn, patch_get_connection):
    """Proper UUIDs → graph edge POSTed."""
    na_id1, na_id2 = _uuid(), _uuid()
    eid1 = seed_contact(test_conn, name="Alice", networking_app_contact_id=na_id1)
    eid2 = seed_contact(test_conn, name="Bob", networking_app_contact_id=na_id2)

    test_conn.execute(
        """INSERT INTO synthesis_entity_links (id, conversation_id, object_type, object_index,
           field_name, original_name, resolved_entity_id, resolution_method, confidence, created_at)
           VALUES (?, 'conv_edge2', 'graph_edge', 0, 'from_entity', 'Alice', ?, 'exact', 1.0, datetime('now'))""",
        (_uuid(), eid1),
    )
    test_conn.execute(
        """INSERT INTO synthesis_entity_links (id, conversation_id, object_type, object_index,
           field_name, original_name, resolved_entity_id, resolution_method, confidence, created_at)
           VALUES (?, 'conv_edge2', 'graph_edge', 0, 'to_entity', 'Bob', ?, 'exact', 1.0, datetime('now'))""",
        (_uuid(), eid2),
    )
    test_conn.commit()

    cid = seed_conversation(test_conn, conv_id="conv_edge2")
    edges = [{"from_entity": "Alice", "to_entity": "Bob", "edge_type": "knows", "strength": 0.7}]
    extraction = _make_extraction(graph_edges=edges)
    mock_api.return_value = (True, None, {"id": "resp-1"})

    from sauron.routing.networking import route_to_networking_app
    route_to_networking_app(cid, extraction, networking_app_contact_id=_uuid())

    rel_calls = [
        c for c in mock_api.call_args_list
        if len(c[0]) > 1 and "/api/contact-relationships" in str(c[0][1])
    ]
    assert len(rel_calls) >= 1, "Valid UUID IDs should be sent to contact-relationships"


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
def test_graph_edge_skipped_for_self_referential(mock_api, mock_store,
                                                  test_conn, patch_get_connection):
    """Same entity on both sides → graph edge skipped."""
    na_id = _uuid()
    eid = seed_contact(test_conn, name="SameGuy", networking_app_contact_id=na_id)

    test_conn.execute(
        """INSERT INTO synthesis_entity_links (id, conversation_id, object_type, object_index,
           field_name, original_name, resolved_entity_id, resolution_method, confidence, created_at)
           VALUES (?, 'conv_self', 'graph_edge', 0, 'from_entity', 'SameGuy', ?, 'exact', 1.0, datetime('now'))""",
        (_uuid(), eid),
    )
    test_conn.execute(
        """INSERT INTO synthesis_entity_links (id, conversation_id, object_type, object_index,
           field_name, original_name, resolved_entity_id, resolution_method, confidence, created_at)
           VALUES (?, 'conv_self', 'graph_edge', 0, 'to_entity', 'SameGuy', ?, 'exact', 1.0, datetime('now'))""",
        (_uuid(), eid),
    )
    test_conn.commit()

    cid = seed_conversation(test_conn, conv_id="conv_self")
    edges = [{"from_entity": "SameGuy", "to_entity": "SameGuy", "edge_type": "knows", "strength": 0.5}]
    extraction = _make_extraction(graph_edges=edges)
    mock_api.return_value = (True, None, {"id": "int-4"})

    from sauron.routing.networking import route_to_networking_app
    route_to_networking_app(cid, extraction, networking_app_contact_id=_uuid())

    rel_calls = [
        c for c in mock_api.call_args_list
        if len(c[0]) > 1 and "/api/contact-relationships" in str(c[0][1])
    ]
    assert len(rel_calls) == 0, "Self-referential edges should be skipped"


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
@patch("sauron.routing.networking._resolve_contact_id_for_entity")
def test_solo_prep_skips_interaction(mock_resolve_entity, mock_api, mock_store,
                                     test_conn, patch_get_connection):
    """Solo mode=prep → no interaction created."""
    na_id = _uuid()
    mock_resolve_entity.return_value = na_id
    mock_api.return_value = (True, None, {"id": "int-solo"})

    cid = seed_conversation(test_conn, conv_id="conv_solo_prep")
    extraction = {
        "synthesis": {
            "summary": "Prep for meeting with Kyle about DeFi proposal",
            "solo_mode": "prep",
            "linked_contact_names": ["Kyle"],
            "topics_discussed": ["DeFi"],
            "graph_edges": [],
        },
        "claims": {},
    }

    from sauron.routing.networking import route_to_networking_app
    route_to_networking_app(cid, extraction)

    interaction_calls = [
        c for c in mock_api.call_args_list
        if len(c[0]) > 1 and "/api/interactions" in str(c[0][1])
    ]
    assert len(interaction_calls) == 0, "Solo prep should skip interaction"


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
@patch("sauron.routing.networking._resolve_contact_id_for_entity")
def test_solo_debrief_skips_thin_summary(mock_resolve_entity, mock_api, mock_store,
                                          test_conn, patch_get_connection):
    """Solo debrief with summary < 30 chars → no interaction."""
    na_id = _uuid()
    mock_resolve_entity.return_value = na_id
    mock_api.return_value = (True, None, {"id": "int-thin"})

    cid = seed_conversation(test_conn, conv_id="conv_thin")
    extraction = {
        "synthesis": {
            "summary": "Quick thought",
            "solo_mode": "debrief",
            "linked_contact_names": ["Kyle"],
            "topics_discussed": [],
            "graph_edges": [],
        },
        "claims": {},
    }

    from sauron.routing.networking import route_to_networking_app
    route_to_networking_app(cid, extraction)

    interaction_calls = [
        c for c in mock_api.call_args_list
        if len(c[0]) > 1 and "/api/interactions" in str(c[0][1])
    ]
    assert len(interaction_calls) == 0, "Thin debrief summary should skip interaction"


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
@patch("sauron.routing.networking._resolve_contact_id_for_entity")
def test_solo_debrief_routes_substantive_summary(mock_resolve_entity, mock_api, mock_store,
                                                   test_conn, patch_get_connection):
    """Solo debrief with long summary → interaction created."""
    na_id = _uuid()
    mock_resolve_entity.return_value = na_id
    mock_api.return_value = (True, None, {"id": "int-sub"})

    cid = seed_conversation(test_conn, conv_id="conv_sub_debrief")
    extraction = {
        "synthesis": {
            "summary": "Had an excellent meeting with Kyle about the DeFi rulemaking proposal and next steps for the team",
            "solo_mode": "debrief",
            "linked_contact_names": ["Kyle"],
            "topics_discussed": ["DeFi"],
            "graph_edges": [],
        },
        "claims": {},
    }

    from sauron.routing.networking import route_to_networking_app
    route_to_networking_app(cid, extraction)

    interaction_calls = [
        c for c in mock_api.call_args_list
        if len(c[0]) > 1 and "/api/interactions" in str(c[0][1])
    ]
    assert len(interaction_calls) >= 1, "Substantive debrief should create interaction"


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
@patch("sauron.routing.networking._resolve_contact_id_for_entity")
def test_solo_multiple_contacts_skips_routing(mock_resolve_entity, mock_api, mock_store,
                                               test_conn, patch_get_connection):
    """Solo capture with 2 resolved contacts → skips routing (ambiguous)."""
    mock_resolve_entity.side_effect = lambda name, conn: _uuid()

    cid = seed_conversation(test_conn, conv_id="conv_multi_solo")
    extraction = {
        "synthesis": {
            "summary": "Discussed Kyle and Jane's project together",
            "solo_mode": "debrief",
            "linked_contact_names": ["Kyle", "Jane"],
            "topics_discussed": [],
            "graph_edges": [],
        },
        "claims": {},
    }

    from sauron.routing.networking import route_to_networking_app
    result = route_to_networking_app(cid, extraction)

    assert result is True  # Not an error, just nothing to route
    mock_api.assert_not_called()


@patch("sauron.routing.networking._store_routing_summary")
@patch("sauron.routing.networking._api_call")
def test_failure_not_logged_on_retry(mock_api, mock_store, test_conn, patch_get_connection):
    """is_retry=True + error → no new routing_log entry."""
    cid = seed_conversation(test_conn, conv_id="conv_retry_nolog")
    extraction = _make_extraction()

    # Make interaction fail
    mock_api.return_value = (False, "500 Internal Server Error", None)

    before = test_conn.execute("SELECT COUNT(*) FROM routing_log").fetchone()[0]

    from sauron.routing.networking import route_to_networking_app
    result = route_to_networking_app(cid, extraction, networking_app_contact_id=_uuid(), is_retry=True)

    after = test_conn.execute("SELECT COUNT(*) FROM routing_log").fetchone()[0]
    assert after == before, "No new routing_log entries should be created on retry"
    assert result is False
