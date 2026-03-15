"""Gate test for Step 3: Clustering + Identity Resolution.

Tests:
1. Build phone index from unified_contacts
2. Check whitelist for ingested threads
3. Cluster messages for whitelisted threads
4. Inspect cluster quality manually
5. Store clusters in DB
6. Re-run status to see updated smoke signals
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import json
from sauron.text.identity import build_phone_index, check_whitelist, resolve_thread_participants
from sauron.text.cluster import cluster_thread_from_db, store_clusters
from sauron.text.status import get_pipeline_status
from sauron.config import DB_PATH

import sqlite3


def main():
    print("=" * 60)
    print("GATE TEST: Clustering + Identity Resolution")
    print("=" * 60)

    # 1. Build phone index
    phone_index = build_phone_index()
    print(f"\n[1] Phone index: {len(phone_index)} contacts with phones")
    # Show a few entries
    for phone, info in list(phone_index.items())[:3]:
        print(f"    {phone} -> {info['name']}")

    # 2. Check whitelist for all ingested threads
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    threads = conn.execute(
        "SELECT id, thread_identifier, thread_type, display_name, participant_phones FROM text_threads"
    ).fetchall()

    print(f"\n[2] Whitelist check for {len(threads)} threads:")
    whitelisted_threads = []
    non_whitelisted = []

    for t in threads:
        participants = json.loads(t["participant_phones"]) if t["participant_phones"] else []
        is_wl = check_whitelist(participants, phone_index)
        name = t["display_name"] or t["thread_identifier"][:30]
        status = "PASS" if is_wl else "FILTERED"

        if is_wl:
            whitelisted_threads.append(t)
            # Show resolved participants
            resolved = resolve_thread_participants(participants, phone_index)
            known_names = [r["name"] for r in resolved if r["known"]]
            unknown = [r["phone"] for r in resolved if not r["known"]]
            print(f"    [{status}] [{t['thread_type']}] {name}")
            if known_names:
                print(f"           Known: {', '.join(known_names)}")
            if unknown:
                print(f"           Unknown: {', '.join(unknown)}")
        else:
            non_whitelisted.append(t)
            print(f"    [{status}] [{t['thread_type']}] {name} (participants: {participants[:2]})")

    print(f"\n    Summary: {len(whitelisted_threads)} whitelisted, {len(non_whitelisted)} filtered")

    if not whitelisted_threads:
        print("\n[WARN] No whitelisted threads! Cannot test clustering.")
        print("       This means no ingested thread participants match unified_contacts phones.")
        print("       Check phone number formats in both tables.")

        # Debug: show sample phones from both sides
        sample_thread_phones = set()
        for t in threads:
            participants = json.loads(t["participant_phones"]) if t["participant_phones"] else []
            sample_thread_phones.update(participants[:3])
        print(f"\n    Sample thread phones: {list(sample_thread_phones)[:5]}")

        sample_contact_phones = list(phone_index.keys())[:5]
        print(f"    Sample contact phones: {sample_contact_phones}")
        conn.close()
        return

    # 3. Cluster whitelisted threads
    print(f"\n[3] Clustering {len(whitelisted_threads)} whitelisted threads:")
    all_clusters = []

    for t in whitelisted_threads[:5]:  # First 5 for gate test
        thread_id = t["id"]
        name = t["display_name"] or t["thread_identifier"][:30]

        clusters = cluster_thread_from_db(thread_id)
        all_clusters.extend([(thread_id, c) for c in clusters])

        print(f"\n    Thread: {name} ({t['thread_type']})")
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM text_messages WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0]
        print(f"    Messages: {msg_count} -> {len(clusters)} clusters")

        for i, c in enumerate(clusters):
            duration_min = (c.end_time - c.start_time).total_seconds() / 60
            print(f"      Cluster {i+1}: {c.message_count} msgs, "
                  f"{c.total_chars} chars, {c.participant_count} participants, "
                  f"{duration_min:.0f}min span")
            print(f"        {c.start_time.strftime('%m/%d %H:%M')} -> {c.end_time.strftime('%m/%d %H:%M')}")

    # 4. Store clusters
    print(f"\n[4] Storing {len(all_clusters)} clusters in DB...")
    total_stored = 0
    total_skipped = 0
    for thread_id, cluster in all_clusters:
        stats = store_clusters(thread_id, [cluster])
        total_stored += stats["stored"]
        total_skipped += stats["skipped_existing"]
    print(f"    Stored: {total_stored}, Skipped (existing): {total_skipped}")

    # 5. Re-run to test dedup
    print(f"\n[5] Re-storing same clusters (dedup test)...")
    total_stored2 = 0
    total_skipped2 = 0
    for thread_id, cluster in all_clusters:
        stats = store_clusters(thread_id, [cluster])
        total_stored2 += stats["stored"]
        total_skipped2 += stats["skipped_existing"]
    print(f"    Stored: {total_stored2}, Skipped (existing): {total_skipped2}")
    if total_stored2 == 0:
        print("    [OK] Cluster dedup working")
    else:
        print("    [WARN] Cluster dedup may not be working")

    # 6. Updated smoke signals
    print(f"\n[6] Updated pipeline status:")
    status = get_pipeline_status()
    print(f"    Health: {status['pipeline_health']}")
    print(f"    Clusters: {status['clusters']['total_clusters']}")
    print(f"    Warnings: {status['warnings']}")
    if status['errors']:
        print(f"    Errors: {status['errors']}")

    conn.close()
    print(f"\n[DONE] Gate test complete.")


if __name__ == "__main__":
    main()
