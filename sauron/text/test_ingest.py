"""Gate test for Step 2: Ingest TextEvents into sauron.db with dedup.

Tests:
1. Read recent messages from chat.db via adapter
2. Ingest them into sauron.db
3. Verify threads and messages are stored correctly
4. Run ingest AGAIN — verify zero duplicates
5. Check watermark advancement
6. Inspect DB state
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sauron.text.adapters.imessage import IMessageAdapter
from sauron.text.ingest import ingest_events, advance_watermark, get_sync_watermark, get_thread_stats
from sauron.config import DB_PATH

import sqlite3


def main():
    print("=" * 60)
    print("GATE TEST: Text Ingest + Dedup")
    print("=" * 60)

    # 1. Read recent messages
    adapter = IMessageAdapter()
    max_rowid = adapter.get_max_rowid()
    watermark = max(0, max_rowid - 200)  # last ~200 messages
    events = adapter.read_since(watermark)
    adapter.close()
    print(f"\n[1] Read {len(events)} TextEvents from chat.db (ROWID {watermark}+)")

    if not events:
        print("[FAIL] No events to ingest.")
        return

    # 2. First ingest
    print(f"\n[2] First ingest ({len(events)} events)...")
    stats1 = ingest_events(events)
    print(f"    Inserted: {stats1['inserted']}")
    print(f"    Skipped (dup): {stats1['skipped_duplicate']}")
    print(f"    Threads created: {stats1['threads_created']}")
    print(f"    Errors: {stats1['errors']}")

    if stats1["errors"] > 0:
        print("[WARN] Errors during first ingest!")

    # 3. Second ingest (same data — should be all duplicates)
    print(f"\n[3] Second ingest (same {len(events)} events — dedup test)...")
    stats2 = ingest_events(events)
    print(f"    Inserted: {stats2['inserted']}")
    print(f"    Skipped (dup): {stats2['skipped_duplicate']}")
    print(f"    Threads created: {stats2['threads_created']}")
    print(f"    Errors: {stats2['errors']}")

    if stats2["inserted"] > 0:
        print("[FAIL] Dedup broken — messages inserted on second pass!")
    else:
        print("[OK] Dedup working — zero inserts on second pass")

    # 4. Advance watermark
    last_event = events[-1]
    advance_watermark("imessage", last_event.source_message_id, stats1["inserted"])
    stored_watermark = get_sync_watermark("imessage")
    print(f"\n[4] Watermark: advanced to {stored_watermark} (expected {last_event.source_message_id})")

    # 5. Inspect DB state
    print(f"\n[5] DB state:")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    thread_count = conn.execute("SELECT COUNT(*) FROM text_threads").fetchone()[0]
    msg_count = conn.execute("SELECT COUNT(*) FROM text_messages").fetchone()[0]
    print(f"    Threads: {thread_count}")
    print(f"    Messages: {msg_count}")

    # Content type breakdown
    cursor = conn.execute("SELECT content_type, COUNT(*) as cnt FROM text_messages GROUP BY content_type ORDER BY cnt DESC")
    print(f"    Content types:")
    for row in cursor:
        print(f"      {row['content_type']}: {row['cnt']}")

    # Thread type breakdown
    cursor = conn.execute("SELECT thread_type, COUNT(*) as cnt FROM text_threads GROUP BY thread_type")
    print(f"    Thread types:")
    for row in cursor:
        print(f"      {row['thread_type']}: {row['cnt']}")

    # Sample messages
    print(f"\n    Sample messages (last 3):")
    cursor = conn.execute("""
        SELECT m.source_message_id, m.direction, m.content_type, m.sender_phone,
               substr(m.content, 1, 60) as preview, t.thread_type
        FROM text_messages m
        JOIN text_threads t ON m.thread_id = t.id
        ORDER BY m.timestamp DESC LIMIT 3
    """)
    for row in cursor:
        arrow = "->" if row["direction"] == "sent" else "<-"
        phone = row["sender_phone"] or "ME"
        print(f"      ROWID {row['source_message_id']} {arrow} {phone} [{row['content_type']}]: {row['preview']}")

    # Review policy
    rule_count = conn.execute("SELECT COUNT(*) FROM review_policy_rules").fetchone()[0]
    print(f"\n    Review policy rules: {rule_count}")

    # Conversations columns
    cursor = conn.execute("PRAGMA table_info(conversations)")
    new_cols = [row[1] for row in cursor if row[1] in ("modality", "current_stage", "stage_detail", "run_status", "blocking_reason")]
    print(f"    Conversations new columns: {new_cols}")

    conn.close()

    # Thread stats from ingest module
    print(f"\n[6] Thread stats (top 5):")
    thread_stats = get_thread_stats()
    for ts in thread_stats[:5]:
        name = ts["display_name"] or ts["thread_identifier"][:30]
        print(f"    [{ts['thread_type']}] {name}: {ts['message_count']} msgs")

    print(f"\n[DONE] Gate test complete.")


if __name__ == "__main__":
    main()
