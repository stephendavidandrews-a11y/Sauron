"""Gate test for Step 1: IMessageAdapter -> TextEvent normalization.

Run from Sauron project root:
  python -m sauron.text.adapters.test_adapter

Checks:
1. Can we connect to chat.db?
2. Can we read recent messages?
3. Are phones E.164 normalized?
4. Are reactions/edits/attachments captured?
5. Are thread types correct?
"""
import sys
from collections import Counter
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sauron.text.adapters.imessage import IMessageAdapter


def main():
    print("=" * 60)
    print("GATE TEST: IMessageAdapter -> TextEvent normalization")
    print("=" * 60)

    adapter = IMessageAdapter()

    # 1. Connection test
    try:
        max_rowid = adapter.get_max_rowid()
        print(f"\n[OK] Connected to chat.db. Max ROWID: {max_rowid}")
    except Exception as e:
        print(f"\n[FAIL] Cannot connect to chat.db: {e}")
        return

    # 2. Read last 50 messages (by ROWID range)
    watermark = max(0, max_rowid - 50)
    events = adapter.read_since(watermark)
    print(f"[OK] Read {len(events)} TextEvents from ROWID {watermark}+")

    if not events:
        print("[WARN] No events returned. Try a lower watermark.")
        adapter.close()
        return

    # 3. Inspect content types
    type_counts = Counter(e.content_type for e in events)
    print(f"\nContent type distribution:")
    for ct, count in type_counts.most_common():
        print(f"  {ct}: {count}")

    # 4. Inspect thread types
    thread_counts = Counter(e.thread_type for e in events)
    print(f"\nThread type distribution:")
    for tt, count in thread_counts.most_common():
        print(f"  {tt}: {count}")

    # 5. Phone normalization check
    phones_ok = 0
    phones_email = 0
    phones_none = 0
    for e in events:
        if e.direction == "sent":
            phones_none += 1  # sent messages have no sender_phone
        elif e.sender_phone and e.sender_phone.startswith("+"):
            phones_ok += 1
        elif e.sender_phone and "@" in e.sender_phone:
            phones_email += 1
        else:
            phones_none += 1
    print(f"\nPhone normalization: {phones_ok} E.164, {phones_email} email, {phones_none} sent/none")

    # 6. Direction check
    dir_counts = Counter(e.direction for e in events)
    print(f"\nDirection: sent={dir_counts.get('sent', 0)}, received={dir_counts.get('received', 0)}")

    # 7. Sample 5 events in detail
    print(f"\n{'=' * 60}")
    print("SAMPLE EVENTS (last 5):")
    print("=" * 60)
    for e in events[-5:]:
        arrow = "->" if e.direction == "sent" else "<-"
        phone = e.sender_phone or "ME"
        content_preview = (e.content or "")[:80]
        if len(e.content or "") > 80:
            content_preview += "..."
        group_tag = " [GROUP]" if e.is_group else ""
        print(f"\n  ROWID: {e.source_message_id}")
        print(f"  {arrow} {phone}{group_tag}")
        print(f"  Type: {e.content_type} | Thread: {e.thread_type}")
        print(f"  Time: {e.timestamp.isoformat()}")
        print(f"  Content: {content_preview}")
        if e.attachment_type:
            print(f"  Attachment: {e.attachment_type} ({e.attachment_filename})")
        if e.attachment_url:
            print(f"  URL: {e.attachment_url}")
        if e.refers_to_message_id:
            print(f"  Refers to: {e.refers_to_message_id}")
        if e.participant_phones:
            print(f"  Thread participants: {e.participant_phones[:3]}{'...' if len(e.participant_phones) > 3 else ''}")
        if e.raw_metadata:
            print(f"  Metadata: {e.raw_metadata}")

    # 8. Thread summary
    print(f"\n{'=' * 60}")
    print("THREAD SUMMARY (top 10):")
    print("=" * 60)
    threads = adapter.get_thread_summary()
    for i, (tid, info) in enumerate(list(threads.items())[:10]):
        gtype = "GROUP" if info["is_group"] else "1on1"
        name = info["display_name"] or tid[:40]
        print(f"  {i+1}. [{gtype}] {name} ({info['message_count']} msgs)")

    adapter.close()
    print(f"\n[DONE] Gate test complete.")


if __name__ == "__main__":
    main()
