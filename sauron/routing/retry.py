"""Periodic retry job for failed routing attempts.

Wired to APScheduler in main.py — runs every 30 minutes.
See Integration Spec v2, Section 13.3.
"""

import json
import logging
from datetime import datetime

from sauron.db.connection import get_connection
from sauron.routing.routing_log import get_failed_routes

logger = logging.getLogger(__name__)


def retry_failed_routes_job():
    """Retry all failed routes that haven't exceeded max attempts.

    Deduplicates by conversation_id (all-or-nothing means one
    conversation_bundle entry per failed conversation). Re-sends
    the stored extraction payload; upsert makes this safe.
    """
    conn = get_connection()
    try:
        failed = get_failed_routes(conn=conn)
    finally:
        conn.close()

    if not failed:
        return

    # Deduplicate by conversation_id
    seen = set()
    to_retry = []
    for route in failed:
        cid = route["conversation_id"]
        if cid not in seen:
            seen.add(cid)
            to_retry.append(route)

    logger.info(f"Retrying {len(to_retry)} failed conversation route(s)")

    from sauron.routing.networking import route_to_networking_app

    success_count = 0
    fail_count = 0

    for route in to_retry:
        conn = get_connection()
        try:
            payload = json.loads(route["payload_json"]) if route["payload_json"] else {}
            cid = route["conversation_id"]

            ok = route_to_networking_app(cid, payload)
            now = datetime.utcnow().isoformat()

            if ok:
                conn.execute(
                    """UPDATE routing_log
                       SET status = 'sent', attempts = attempts + 1, last_attempt_at = ?
                       WHERE id = ?""",
                    (now, route["id"]),
                )
                conn.execute(
                    "UPDATE conversations SET routed_at = datetime('now') WHERE id = ?",
                    (cid,),
                )
                conn.commit()
                success_count += 1
            else:
                # route_to_networking_app already logged a new failure entry;
                # bump attempts on the original entry
                conn.execute(
                    """UPDATE routing_log
                       SET attempts = attempts + 1, last_attempt_at = ?
                       WHERE id = ?""",
                    (now, route["id"]),
                )
                conn.commit()
                fail_count += 1
        except Exception:
            logger.exception(f"Retry failed for conversation {route['conversation_id'][:8]}")
            fail_count += 1
        finally:
            conn.close()

    logger.info(f"Routing retry complete: {success_count} succeeded, {fail_count} failed")
