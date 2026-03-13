"""Route extraction results to the Networking App — shared core utilities.

Extracted from sauron/routing/networking.py (stability refactor).
"""

import json as _json
import logging

import httpx

from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=5.0)


@dataclass
class RoutingSummary:
    """Per-routing-run health snapshot stored in routing_summaries table.

    Lane statuses:
        success             — lane executed, all API calls succeeded
        failed              — lane executed, one or more API calls failed
        skipped_no_data     — lane had nothing to route (healthy, NOT degraded)
        skipped_blocked     — lane had data but entity unresolved/held (degraded)
        skipped_unresolved  — lane had data but entity resolution failed (degraded)
        skipped_low_confidence — lane had data but below confidence threshold (degraded)

    Counting rules:
        warning_count  = count of degraded-but-not-failed secondary lanes
                         (skipped_blocked, skipped_unresolved, skipped_low_confidence)
                         Does NOT include skipped_no_data or failed.
        error_count    = count of failed secondary lanes + count of failed core lanes

    final_state semantics:
        success        — all core lanes succeeded, no degraded secondary lanes.
                         Lanes with skipped_no_data do NOT prevent success.
        success_with_partial_secondary_loss
                       — all core lanes succeeded, but one or more secondary lanes
                         are in a DEGRADED_STATUSES state (failed, skipped_blocked,
                         skipped_unresolved, or skipped_low_confidence).
                         NOTE: this means warning_count can be 0 while final_state
                         is success_with_partial_secondary_loss — that happens when
                         secondary lanes failed (counted in error_count) but none
                         were in the warning-only degraded states.
        failed         — one or more core lanes failed. Entire routing is a failure.
    """
    conversation_id: str
    routing_attempt_id: str  # UUID
    trigger_type: str  # initial, reroute, replay, solo
    final_state: str  # success, success_with_partial_secondary_loss, failed
    core_lanes: list = field(default_factory=list)  # [{name, status, error?}]
    secondary_lanes: list = field(default_factory=list)  # [{name, status, reason?}]
    pending_entities: list = field(default_factory=list)  # blocked entity names
    warning_count: int = 0
    error_count: int = 0


def _store_routing_summary(summary: RoutingSummary, conn=None):
    """Persist routing summary to the routing_summaries table."""
    import json as _js
    from sauron.db.connection import get_connection
    db_conn = conn or get_connection()
    close_conn = conn is None
    try:
        db_conn.execute(
            """INSERT INTO routing_summaries
               (conversation_id, routing_attempt_id, trigger_type, final_state,
                core_lanes, secondary_lanes, pending_entities, warning_count, error_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (summary.conversation_id, summary.routing_attempt_id, summary.trigger_type,
             summary.final_state, _js.dumps(summary.core_lanes), _js.dumps(summary.secondary_lanes),
             _js.dumps(summary.pending_entities), summary.warning_count, summary.error_count)
        )
        db_conn.commit()
    finally:
        if close_conn:
            db_conn.close()


def _api_call(
    method: str, url: str, payload: dict
) -> tuple[bool, str | None, dict | None]:
    """Execute a single API call. Returns (success, error_or_None, response_body_or_None).

    Third element is the parsed JSON response body (dict) when available,
    used to inspect resolution details on error (e.g. provisional_suggestion).
    """
    try:
        if method == "POST":
            resp = httpx.post(url, json=payload, timeout=TIMEOUT)
        elif method == "PUT":
            resp = httpx.put(url, json=payload, timeout=TIMEOUT)
        elif method == "PATCH":
            resp = httpx.patch(url, json=payload, timeout=TIMEOUT)
        elif method == "GET":
            resp = httpx.get(url, timeout=TIMEOUT)
        else:
            return False, f"Unsupported method: {method}", None

        resp_body = None
        try:
            resp_body = resp.json()
        except Exception:
            pass

        if resp.status_code < 300:
            return True, None, resp_body
        else:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}", resp_body
    except httpx.ConnectError:
        return False, "ConnectError: Networking app not reachable", None
    except Exception as e:
        return False, str(e)[:300], None
