"""Quick preprocessor test — no API calls."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import sqlite3
from sauron.config import DB_PATH
from sauron.text.identity import build_phone_index
from sauron.text.preprocessor import format_cluster_for_extraction, build_text_participant_roster

phone_index = build_phone_index()

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
clusters = conn.execute(
    """SELECT tc.id, tc.message_count, tt.display_name, tt.thread_type
       FROM text_clusters tc
       JOIN text_threads tt ON tc.thread_id = tt.id
       ORDER BY tc.message_count DESC"""
).fetchall()
conn.close()

print(f"Found {len(clusters)} clusters")

for i, c in enumerate(clusters[:3]):
    cid = c["id"]
    name = c["display_name"]
    mcount = c["message_count"]
    ttype = c["thread_type"]
    print(f"\n--- Cluster {i+1}: {name} ({mcount} msgs, {ttype}) ---")

    result = format_cluster_for_extraction(cid, phone_index=phone_index)
    print(f"Lines: {result['line_count']}, Chars: {result['total_chars']}")
    print(f"Participants: {result['participant_names']}")

    lines = result["transcript"].split("\n")
    print("\nTranscript preview:")
    for line in lines[:8]:
        print(f"  {line}")
    if len(lines) > 8:
        print(f"  ... ({len(lines) - 8} more)")

    roster = build_text_participant_roster(result["participant_map"])
    if roster:
        print("\nRoster preview:")
        for line in roster.split("\n")[:6]:
            print(f"  {line}")

print("\n[OK] Preprocessor working")
