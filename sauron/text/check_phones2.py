"""Check phone normalization using the actual build_phone_index function."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sauron.text.identity import build_phone_index

idx = build_phone_index()
print(f"Phone index: {len(idx)} entries")

# Check specifically for the 4 failing contacts
import sqlite3
from sauron.config import DB_PATH
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
for name in ['Elizabeth Shults', 'John F. Schaefer', 'John K. Adams', 'Luke Garoufalis', 'Catherine Cole', 'Will Simpson']:
    row = conn.execute('SELECT id, phone_number FROM unified_contacts WHERE canonical_name = ?', (name,)).fetchone()
    if row:
        found = False
        for phone, info in idx.items():
            if info['contact_id'] == row['id']:
                found = True
                print(f"  OK: {name} -> {phone}")
                break
        if not found:
            print(f"  MISSING: {name} ({row['phone_number']})")
conn.close()
