"""Check which phones fail normalization."""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import sqlite3
from sauron.config import DB_PATH
from sauron.text.identity import _normalize_to_e164

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT canonical_name, phone_number FROM unified_contacts WHERE phone_number IS NOT NULL"
).fetchall()

failed = []
multi = 0
total_entries = 0
for r in rows:
    raw = (r["phone_number"] or "").strip()
    if not raw:
        continue

    parts = re.split(r'[,|;]', raw)
    if len(parts) > 1:
        multi += 1

    any_ok = False
    for part in parts:
        cleaned = re.sub(r'\([^)]*\)', '', part).strip()
        if cleaned:
            norm = _normalize_to_e164(cleaned)
            if norm:
                any_ok = True
                total_entries += 1

    if not any_ok:
        failed.append((r["canonical_name"], raw))

print(f"Total contacts with phones: {len(rows)}")
print(f"Total index entries: {total_entries}")
print(f"Multi-number contacts: {multi}")
print(f"Failed normalization: {len(failed)}")
for name, phone in failed:
    print(f"  {name}: {phone}")
conn.close()
