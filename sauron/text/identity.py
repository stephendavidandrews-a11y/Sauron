"""Phone -> contact resolution for the text pipeline.

Primary: lookup in unified_contacts (synced from Networking App).
Fallback: pyobjc CNContactStore query for display name only
(headless, no AppleScript, no GUI dependency).

The whitelist check also lives here: a thread passes the whitelist
if at least one participant maps to a known unified_contact.
"""

import logging
import re
import sqlite3

from sauron.db.connection import get_connection as _db_conn
from functools import lru_cache

from sauron.config import DB_PATH

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


def _normalize_to_e164(raw: str) -> str | None:
    """Normalize a phone string to E.164 format (+1XXXXXXXXXX for US).

    Handles:
    - Already E.164: +12029246539 → +12029246539
    - Dashed: 858-414-8454 → +18584148454
    - Parenthetical: (202) 598-2858 → +12025982858
    - Dotted: 941.916.0309 → +19419160309
    - Bare 10-digit: 6124370032 → +16124370032
    - Bare 11-digit with leading 1: 17726511186 → +17726511186
    - Space-separated: 212 970 8021 → +12129708021

    Returns E.164 string or None if unparseable.
    """
    try:
        import phonenumbers
        # Try phonenumbers library first (most robust)
        parsed = phonenumbers.parse(raw, "US")
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass

    # Fallback: strip to digits and construct E.164
    digits = re.sub(r'[^\d]', '', raw)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"+{digits}"
    elif len(digits) > 11:
        # Could be international — try with +
        try:
            import phonenumbers
            parsed = phonenumbers.parse(f"+{digits}")
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except Exception:
            pass

    return None


def build_phone_index(db_path=None) -> dict[str, dict]:
    """Build a phone -> contact lookup from unified_contacts.

    Returns dict: {
        "+12025551234": {
            "contact_id": "uuid",
            "name": "Jane Doe",
            "phone": "+12025551234",
        },
        ...
    }

    Handles diverse phone formats in unified_contacts:
    - E.164, dashed, parenthetical, dotted, bare digits
    - Multi-number strings: "312-395-4015 (office), 419-304-8550 (cell)"
    All normalized to E.164 for consistent matching with text_messages.
    """
    conn = _get_conn(db_path)
    try:
        cursor = conn.execute(
            "SELECT id, canonical_name, phone_number FROM unified_contacts WHERE phone_number IS NOT NULL"
        )
        index: dict[str, dict] = {}
        contacts_processed = 0
        multi_number_contacts = 0

        for row in cursor:
            raw_phone = (row["phone_number"] or "").strip()
            if not raw_phone:
                continue

            contacts_processed += 1
            name = row["canonical_name"]
            contact_id = row["id"]

            # Split multi-number strings on comma, pipe, semicolon
            # e.g. "312-395-4015 (office), 419-304-8550 (cell)"
            # e.g. "202-514-8069 (D) | 202-514-1057 (O)"
            phone_parts = re.split(r'[,|;]', raw_phone)

            if len(phone_parts) > 1:
                multi_number_contacts += 1

            matched = False
            for part in phone_parts:
                # Strip labels like "(office)", "(cell)", "(D)"
                cleaned = re.sub(r'\([^)\d]*[a-zA-Z][^)]*\)', '', part).strip()
                if not cleaned:
                    continue

                normalized = _normalize_to_e164(cleaned)
                if normalized:
                    index[normalized] = {
                        "contact_id": contact_id,
                        "name": name,
                        "phone": normalized,
                    }
                    matched = True

            if not matched:
                logger.debug("Could not normalize any phone for %s: %s", name, raw_phone)

        logger.info(
            "Phone index built: %d entries from %d contacts (%d multi-number)",
            len(index), contacts_processed, multi_number_contacts,
        )
        return index
    finally:
        conn.close()


def resolve_phone(
    phone: str,
    phone_index: dict[str, dict],
) -> tuple[str | None, str | None]:
    """Resolve a phone number to (contact_id, display_name).

    Returns (contact_id, name) from unified_contacts if found.
    Returns (None, fallback_name) if pyobjc lookup succeeds.
    Returns (None, None) if completely unknown.
    """
    # Primary: direct lookup
    if phone in phone_index:
        entry = phone_index[phone]
        return entry["contact_id"], entry["name"]

    # Try normalizing the input phone in case format differs
    normalized = _normalize_to_e164(phone)
    if normalized and normalized != phone and normalized in phone_index:
        entry = phone_index[normalized]
        return entry["contact_id"], entry["name"]

    # Fallback: pyobjc CNContactStore (macOS only, headless)
    fallback_name = _pyobjc_lookup(phone)
    if fallback_name:
        return None, fallback_name

    return None, None


@lru_cache(maxsize=512)
def _pyobjc_lookup(phone: str) -> str | None:
    """Query macOS Contacts via pyobjc for a display name.

    This is a fallback for contacts not in unified_contacts.
    Headless — no AppleScript, no GUI, no -600 errors.
    Returns display name or None.
    """
    try:
        from Contacts import (
            CNContactStore,
            CNContactFetchRequest,
            CNContactGivenNameKey,
            CNContactFamilyNameKey,
            CNContactPhoneNumbersKey,
        )
        from Foundation import NSPredicate
    except ImportError:
        # pyobjc-framework-Contacts not installed
        logger.debug("pyobjc-framework-Contacts not available, skipping fallback lookup")
        return None

    try:
        store = CNContactStore.alloc().init()
        keys = [CNContactGivenNameKey, CNContactFamilyNameKey, CNContactPhoneNumbersKey]
        request = CNContactFetchRequest.alloc().initWithKeysToFetch_(keys)

        results = []

        def handler(contact, stop):
            for phone_value in contact.phoneNumbers():
                digits = phone_value.value().stringValue()
                # Simple comparison: strip non-digits and compare last 10
                clean = "".join(c for c in digits if c.isdigit())
                phone_clean = "".join(c for c in phone if c.isdigit())
                if clean[-10:] == phone_clean[-10:] and len(clean) >= 10:
                    given = contact.givenName() or ""
                    family = contact.familyName() or ""
                    full = f"{given} {family}".strip()
                    if full:
                        results.append(full)
                    return

        store.enumerateContactsWithFetchRequest_error_usingBlock_(request, None, handler)
        return results[0] if results else None
    except Exception as e:
        logger.debug("pyobjc contact lookup failed: %s", e)
        return None


def check_whitelist(
    participant_phones: list[str],
    phone_index: dict[str, dict],
) -> bool:
    """Check if a thread passes the whitelist.

    A thread is whitelisted if at least one participant is:
    1. A known unified_contact (from Networking App), OR
    2. Found in macOS/iPhone Contacts (via pyobjc CNContactStore).
    Self (sent messages) always passes.
    """
    for phone in participant_phones:
        if phone in phone_index:
            return True
        # Also try normalizing in case of format mismatch
        normalized = _normalize_to_e164(phone)
        if normalized and normalized in phone_index:
            return True
        # Fallback: check macOS/iPhone Contacts
        if _pyobjc_lookup(phone):
            logger.info("Whitelisted %s via macOS Contacts", phone)
            return True
    return False


def resolve_thread_participants(
    participant_phones: list[str],
    phone_index: dict[str, dict],
) -> list[dict]:
    """Resolve all participants in a thread.

    Returns list of dicts:
    [
        {"phone": "+1...", "contact_id": "uuid" | None, "name": "Jane" | None, "known": True/False},
        ...
    ]

    This is used for:
    1. Populating text_threads.participant_contact_ids
    2. Identifying unknown numbers for the pending_contacts queue
    3. Setting sender_contact_id on text_messages
    """
    resolved = []
    for phone in participant_phones:
        contact_id, name = resolve_phone(phone, phone_index)
        resolved.append({
            "phone": phone,
            "contact_id": contact_id,
            "name": name,
            "known": contact_id is not None,
        })
    return resolved
