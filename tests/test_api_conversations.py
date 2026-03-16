"""Test conversation API endpoints — Audit Fix #5."""

import uuid
import pytest
from tests.helpers import seed_conversation


def test_list_conversations_empty(app_client):
    """200 with empty list when no conversations exist."""
    resp = app_client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_conversations_with_data(app_client, patch_get_connection):
    """3 seeded conversations → 3 returned."""
    conn = patch_get_connection()
    for i in range(3):
        seed_conversation(conn, conv_id=f"conv_list_{i}", status="completed")
    conn.close()

    resp = app_client.get("/api/conversations")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_list_conversations_status_filter(app_client, patch_get_connection):
    """Status filter returns only matching conversations."""
    conn = patch_get_connection()
    seed_conversation(conn, conv_id="conv_f1", status="completed")
    seed_conversation(conn, conv_id="conv_f2", status="awaiting_claim_review")
    seed_conversation(conn, conv_id="conv_f3", status="completed")
    conn.close()

    resp = app_client.get("/api/conversations?status=completed")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_conversations_limit_too_high(app_client):
    """limit=999 → 422 validation error."""
    resp = app_client.get("/api/conversations?limit=999")
    assert resp.status_code == 422


def test_list_conversations_limit_too_low(app_client):
    """limit=0 → 422 validation error."""
    resp = app_client.get("/api/conversations?limit=0")
    assert resp.status_code == 422


def test_list_conversations_offset_negative(app_client):
    """offset=-1 → 422 validation error."""
    resp = app_client.get("/api/conversations?offset=-1")
    assert resp.status_code == 422


def test_needs_review_returns_correct_status(app_client, patch_get_connection):
    """needs-review returns only awaiting_claim_review conversations."""
    conn = patch_get_connection()
    seed_conversation(conn, conv_id="conv_nr1", status="awaiting_claim_review")
    seed_conversation(conn, conv_id="conv_nr2", status="completed")
    seed_conversation(conn, conv_id="conv_nr3", status="awaiting_claim_review")
    conn.close()

    resp = app_client.get("/api/conversations/needs-review")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for item in data:
        assert item["processing_status"] == "awaiting_claim_review"


def test_queue_counts_returns_buckets(app_client, patch_get_connection):
    """queue-counts returns all expected keys."""
    conn = patch_get_connection()
    seed_conversation(conn, conv_id="conv_qc1", status="awaiting_speaker_review")
    seed_conversation(conn, conv_id="conv_qc2", status="awaiting_claim_review")
    seed_conversation(conn, conv_id="conv_qc3", status="pending")
    conn.close()

    resp = app_client.get("/api/conversations/queue-counts")
    assert resp.status_code == 200
    data = resp.json()
    assert "speaker_review" in data
    assert "triage_review" in data
    assert "claim_review" in data
    assert "processing" in data
    assert "pending" in data
    assert data["speaker_review"] == 1
    assert data["claim_review"] == 1
    assert data["pending"] == 1


def test_get_conversation_not_found(app_client):
    """404 for nonexistent conversation."""
    resp = app_client.get("/api/conversations/nonexistent-id")
    assert resp.status_code == 404
