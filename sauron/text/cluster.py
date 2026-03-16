"""Conversation clustering — overnight-split algorithm.

Segments a thread's messages into conversation clusters. Each cluster
becomes the unit of extraction and review.

PRINCIPLES:
- Soft intraday continuity: same-day messages generally stay together
- Overnight = default split boundary (5 AM local)
- 8-hour hard intraday split (12 for group chats)
- Short but meaningful clusters are valid (no message-count minimum)
- Low-substance clusters preserved in light form (Lane 0/1)
- Clusters are corrigible: merge/split in review is always available
"""

import logging
import sqlite3

from sauron.db.connection import get_connection as _db_conn
import uuid
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# User's local timezone for overnight boundary calculation
LOCAL_TZ = ZoneInfo("America/New_York")

from sauron.config import DB_PATH
from sauron.text.models import ClusterConfig, MessageCluster

logger = logging.getLogger(__name__)


def _get_conn(db_path=None) -> sqlite3.Connection:
    """Get a DB connection with FK/WAL/busy_timeout pragmas."""
    if db_path:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn
    return _db_conn()


def cluster_thread_messages(
    messages: list[dict],
    thread_type: str,
    config: ClusterConfig | None = None,
) -> list[MessageCluster]:
    """Segment a thread's messages into conversation clusters.

    Args:
        messages: list of dicts with at least 'id', 'source_message_id',
                  'timestamp' (ISO string), 'content', 'sender_phone',
                  'content_type' fields. Must be sorted by timestamp.
        thread_type: '1on1' or 'group'
        config: clustering config (defaults to ClusterConfig())

    Returns:
        list of MessageCluster objects with exact message membership.
    """
    if not messages:
        return []

    config = config or ClusterConfig()
    hard_split = config.group_hard_split_hours if thread_type == "group" else config.hard_split_hours

    # Sort by timestamp (should already be sorted, but enforce)
    sorted_msgs = sorted(messages, key=lambda m: m["timestamp"])

    clusters: list[MessageCluster] = []
    current_msgs: list[dict] = [sorted_msgs[0]]

    for i in range(1, len(sorted_msgs)):
        prev_msg = sorted_msgs[i - 1]
        curr_msg = sorted_msgs[i]

        prev_ts = _parse_ts(prev_msg["timestamp"])
        curr_ts = _parse_ts(curr_msg["timestamp"])

        should_split = False
        split_reason = None

        # Check overnight boundary
        if _crosses_overnight(prev_ts, curr_ts, config.day_boundary_hour):
            should_split = True
            split_reason = "overnight"

        # Check hard gap threshold
        gap_hours = (curr_ts - prev_ts).total_seconds() / 3600
        if gap_hours >= hard_split:
            should_split = True
            split_reason = f"gap_{gap_hours:.1f}h"

        # Safety cap: max messages per cluster
        if len(current_msgs) >= config.max_cluster_messages:
            should_split = True
            split_reason = "max_messages"

        if should_split:
            # Finalize current cluster
            cluster = _build_cluster(current_msgs, thread_type)
            clusters.append(cluster)
            logger.debug(
                "Split cluster: %d msgs, %s -> %s (reason: %s)",
                len(current_msgs),
                current_msgs[0]["timestamp"][:16],
                current_msgs[-1]["timestamp"][:16],
                split_reason,
            )
            current_msgs = [curr_msg]
        else:
            current_msgs.append(curr_msg)

    # Finalize last cluster
    if current_msgs:
        clusters.append(_build_cluster(current_msgs, thread_type))

    logger.info(
        "Clustered %d messages into %d clusters (thread_type=%s)",
        len(sorted_msgs), len(clusters), thread_type,
    )
    return clusters


def _build_cluster(messages: list[dict], thread_type: str) -> MessageCluster:
    """Build a MessageCluster from a list of message dicts."""
    msg_ids = [m["source_message_id"] for m in messages]
    phones = set()
    total_chars = 0
    for m in messages:
        if m.get("sender_phone"):
            phones.add(m["sender_phone"])
        content = m.get("content") or ""
        total_chars += len(content)

    first_ts = _parse_ts(messages[0]["timestamp"])
    last_ts = _parse_ts(messages[-1]["timestamp"])

    return MessageCluster(
        cluster_id=str(uuid.uuid4()),
        thread_identifier=messages[0].get("thread_identifier", ""),
        thread_type=thread_type,
        message_ids=msg_ids,
        start_time=first_ts,
        end_time=last_ts,
        message_count=len(messages),
        total_chars=total_chars,
        participant_phones=list(phones),
        participant_count=len(phones) + 1,  # +1 for self
    )


def _parse_ts(ts_str: str) -> datetime:
    """Parse an ISO timestamp string to datetime."""
    if isinstance(ts_str, datetime):
        return ts_str
    # Handle various ISO formats
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        # Fallback: strip microseconds if malformed
        return datetime.fromisoformat(ts_str[:19])


def _crosses_overnight(
    prev_ts: datetime,
    curr_ts: datetime,
    boundary_hour: int,
) -> bool:
    """Check if two timestamps cross an overnight boundary.

    The boundary is at boundary_hour (default 5 AM). So messages at
    11 PM and 1 AM are same-day if gap is small. But messages at
    11 PM and 6 AM cross the overnight boundary.
    """
    # Normalize to local date using the boundary hour
    prev_day = _boundary_date(prev_ts, boundary_hour)
    curr_day = _boundary_date(curr_ts, boundary_hour)
    return prev_day != curr_day


def _boundary_date(ts: datetime, boundary_hour: int) -> str:
    """Get the 'logical date' for a timestamp given a boundary hour.

    Before the boundary hour, the timestamp belongs to the previous day.
    Converts UTC timestamps to local timezone (Eastern) before checking.
    """
    # Convert to local timezone for overnight boundary check
    if ts.tzinfo is not None:
        local_ts = ts.astimezone(LOCAL_TZ)
    else:
        # Assume UTC if no timezone info
        local_ts = ts.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)

    if local_ts.hour < boundary_hour:
        adjusted = local_ts - timedelta(days=1)
    else:
        adjusted = local_ts
    return adjusted.strftime("%Y-%m-%d")


# ── DB operations for storing clusters ──

def cluster_thread_from_db(
    thread_id: str,
    since: datetime | None = None,
    config: ClusterConfig | None = None,
    db_path=None,
) -> list[MessageCluster]:
    """Load a thread's messages from DB and cluster them.

    Args:
        thread_id: text_threads.id
        since: only cluster messages after this timestamp (for incremental)
        config: clustering config

    Returns list of MessageCluster objects.
    """
    conn = _get_conn(db_path)
    try:
        # Get thread type
        thread_row = conn.execute(
            "SELECT thread_type, thread_identifier FROM text_threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if not thread_row:
            logger.warning("Thread %s not found", thread_id)
            return []

        thread_type = thread_row["thread_type"]

        # Load messages
        if since:
            cursor = conn.execute(
                """SELECT id, source_message_id, timestamp, content, content_type,
                          sender_phone, direction
                   FROM text_messages
                   WHERE thread_id = ? AND timestamp >= ?
                   ORDER BY timestamp ASC""",
                (thread_id, since.isoformat()),
            )
        else:
            cursor = conn.execute(
                """SELECT id, source_message_id, timestamp, content, content_type,
                          sender_phone, direction
                   FROM text_messages
                   WHERE thread_id = ?
                   ORDER BY timestamp ASC""",
                (thread_id,),
            )

        messages = [dict(row) for row in cursor]
        if not messages:
            return []

        # Add thread_identifier to each message (needed by _build_cluster)
        for m in messages:
            m["thread_identifier"] = thread_row["thread_identifier"]

        return cluster_thread_messages(messages, thread_type, config)
    finally:
        conn.close()


def store_clusters(
    thread_id: str,
    clusters: list[MessageCluster],
    db_path=None,
) -> dict:
    """Store clusters and their message membership in DB.

    Returns stats: {"stored": int, "skipped_existing": int}

    Idempotent: checks if an identical cluster (same message set) already
    exists before creating. This prevents duplicate clusters on re-run.
    """
    conn = _get_conn(db_path)
    stats = {"stored": 0, "skipped_existing": 0}

    try:
        for cluster in clusters:
            # Check for existing cluster with same message set
            msg_set_key = ",".join(sorted(cluster.message_ids))
            existing = conn.execute(
                """SELECT tc.id FROM text_clusters tc
                   JOIN text_cluster_messages tcm ON tc.id = tcm.cluster_id
                   WHERE tc.thread_id = ?
                   GROUP BY tc.id
                   HAVING GROUP_CONCAT(tcm.message_id ORDER BY tcm.ordinal) = ?""",
                (thread_id, msg_set_key),
            ).fetchone()

            # Simpler dedup: check if any cluster overlaps with this time range
            # and has same message count (good enough for Phase 1)
            if not existing:
                existing = conn.execute(
                    """SELECT id FROM text_clusters
                       WHERE thread_id = ?
                         AND start_time = ?
                         AND end_time = ?
                         AND message_count = ?""",
                    (thread_id, cluster.start_time.isoformat(),
                     cluster.end_time.isoformat(), cluster.message_count),
                ).fetchone()

            if existing:
                stats["skipped_existing"] += 1
                continue

            # Store cluster
            conn.execute(
                """INSERT INTO text_clusters
                   (id, thread_id, cluster_method, depth_lane,
                    start_time, end_time, message_count, participant_count,
                    merged_from, split_from)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cluster.cluster_id,
                    thread_id,
                    cluster.cluster_method,
                    cluster.depth_lane,
                    cluster.start_time.isoformat(),
                    cluster.end_time.isoformat(),
                    cluster.message_count,
                    cluster.participant_count,
                    None,  # merged_from
                    None,  # split_from
                ),
            )

            # Store message membership with ordinals
            # Need to map source_message_id -> text_messages.id
            for ordinal, source_msg_id in enumerate(cluster.message_ids):
                msg_row = conn.execute(
                    "SELECT id FROM text_messages WHERE thread_id = ? AND source_message_id = ?",
                    (thread_id, source_msg_id),
                ).fetchone()
                if msg_row:
                    conn.execute(
                        """INSERT OR IGNORE INTO text_cluster_messages
                           (cluster_id, message_id, ordinal)
                           VALUES (?, ?, ?)""",
                        (cluster.cluster_id, msg_row["id"], ordinal),
                    )

            stats["stored"] += 1

        conn.commit()
        logger.info(
            "Stored %d clusters for thread %s (%d skipped existing)",
            stats["stored"], thread_id, stats["skipped_existing"],
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return stats
