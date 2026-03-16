"""iMessage adapter — reads macOS chat.db and produces normalized TextEvents.

This is the ONLY file in Sauron that knows about chat.db schema,
attributedBody blob format, or Apple-specific message structure. After
normalization, the rest of the text pipeline works with source-agnostic
TextEvent objects.

Requires Full Disk Access for the calling process.

chat.db schema (macOS Sequoia):
- message: ROWID, text, attributedBody (BLOB), date (nanoseconds since 2001),
           is_from_me, handle_id, cache_roomnames, associated_message_type,
           associated_message_guid, cache_has_attachments, date_edited,
           date_retracted, reply_to_guid, thread_originator_guid
- handle: ROWID, id (phone/email), service
- chat: ROWID, chat_identifier, display_name, style (43=group)
- chat_handle_join: chat_id -> handle_id
- chat_message_join: chat_id -> message_id
- attachment: ROWID, filename, mime_type, uti, transfer_name, total_bytes
- message_attachment_join: message_id -> attachment_id
"""

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import phonenumbers

from sauron.text.models import TextEvent

logger = logging.getLogger(__name__)

# Apple Core Data epoch: 2001-01-01 00:00:00 UTC
_APPLE_EPOCH_OFFSET = 978307200

# Date floor for text sync — do not process messages before this date.
# Value is nanoseconds since 2001-01-01 (chat.db format).
# March 1, 2026 00:00:00 UTC
TEXT_SYNC_EARLIEST_NANOS = 794016000000000000

# Tapback reaction types (associated_message_type)
# 2000-2006 = add reaction, 3000-3006 = remove reaction
_REACTION_TYPES = {
    2000: "love", 2001: "like", 2002: "dislike",
    2003: "laugh", 2004: "emphasize", 2005: "question",
    2006: "thumbs_down",
    3000: "remove_love", 3001: "remove_like", 3002: "remove_dislike",
    3003: "remove_laugh", 3004: "remove_emphasize", 3005: "remove_question",
    3006: "remove_thumbs_down",
}

# URL pattern for detecting link messages
_URL_PATTERN = re.compile(
    r'https?://[^\s<>"\x27\)]+',
    re.IGNORECASE,
)

# Default chat.db path on macOS
_DEFAULT_CHATDB_PATH = Path.home() / "Library" / "Messages" / "chat.db"


def _apple_ts_to_datetime(ts: int | None) -> datetime | None:
    """Convert Apple Core Data nanosecond timestamp to UTC datetime."""
    if not ts or ts == 0:
        return None
    try:
        seconds = ts / 1_000_000_000
        unix_ts = seconds + _APPLE_EPOCH_OFFSET
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _normalize_phone(raw: str, default_region: str = "US") -> str | None:
    """Normalize phone number to E.164 format. Returns None if unparseable."""
    if not raw:
        return None
    cleaned = raw.strip()
    if "@" in cleaned:
        return None  # email handle, not a phone
    try:
        parsed = phonenumbers.parse(cleaned, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    # Fallback: strip non-digits, try common US formats
    digits = re.sub(r"[^\d+]", "", cleaned)
    if len(digits) < 7:
        return None
    try:
        if len(digits) == 11 and digits.startswith("1"):
            digits = "+" + digits
        elif len(digits) == 10:
            digits = "+1" + digits
        parsed = phonenumbers.parse(digits, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None


def _extract_text_from_attributed_body(blob: bytes) -> str | None:
    """Extract plain text from attributedBody typedstream blob.

    macOS Sequoia stores iMessage text in attributedBody as a serialized
    NSAttributedString. The UTF-8 text sits after the NSString class marker
    and a 0x2b byte, prefixed by a variable-length integer.
    """
    if not blob:
        return None
    try:
        idx = blob.find(b"NSString")
        if idx < 0:
            return None
        rest = blob[idx + 8:]
        plus_idx = rest.find(b"\x2b")
        if plus_idx < 0 or plus_idx > 10:
            return None
        pos = plus_idx + 1
        length_byte = rest[pos]
        if length_byte == 0x81:
            text_len = int.from_bytes(rest[pos + 1:pos + 3], "little")
            text_start = pos + 3
        elif length_byte == 0x82:
            text_len = int.from_bytes(rest[pos + 1:pos + 4], "little")
            text_start = pos + 4
        elif length_byte == 0x83:
            text_len = int.from_bytes(rest[pos + 1:pos + 5], "little")
            text_start = pos + 5
        else:
            text_len = length_byte
            text_start = pos + 1
        if text_len <= 0 or text_start + text_len > len(rest):
            return None
        text = rest[text_start:text_start + text_len].decode("utf-8", errors="replace")
        return text.strip() if text else None
    except Exception:
        return None


def _classify_attachment(mime_type: str | None, uti: str | None, filename: str | None) -> str | None:
    """Classify attachment into a simple type string."""
    mime = (mime_type or "").lower()
    u = (uti or "").lower()
    fn = (filename or "").lower()
    if mime.startswith("image/") or "image" in u:
        return "image"
    if mime.startswith("video/") or "movie" in u or "video" in u:
        return "video"
    if mime.startswith("audio/") or "audio" in u:
        return "audio"
    if mime == "application/pdf" or fn.endswith(".pdf"):
        return "pdf"
    if any(fn.endswith(ext) for ext in (".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")):
        return "document"
    if mime or u or fn:
        return "other"
    return None


class IMessageAdapter:
    """Reads macOS chat.db and produces normalized TextEvents.

    This is the ONLY class that knows about chat.db schema. All output
    is source-agnostic TextEvent objects.
    """

    def __init__(self, chatdb_path: str | Path | None = None):
        self._path = str(chatdb_path or _DEFAULT_CHATDB_PATH)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
            self._conn.execute("PRAGMA query_only = ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, *args):
        self.close()

    # -- Thread participant lookup --

    def _get_thread_participants(self, conn: sqlite3.Connection) -> dict[str, list[str]]:
        """Build mapping: chat_identifier -> list of participant phones (E.164)."""
        cursor = conn.execute("""
            SELECT c.chat_identifier, h.id as handle_id
            FROM chat c
            JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
            JOIN handle h ON chj.handle_id = h.ROWID
        """)
        threads: dict[str, list[str]] = {}
        for row in cursor:
            chat_id = row["chat_identifier"]
            phone = _normalize_phone(row["handle_id"])
            if phone:
                threads.setdefault(chat_id, []).append(phone)
        # Deduplicate participant lists
        return {k: list(dict.fromkeys(v)) for k, v in threads.items()}

    def _get_chat_display_names(self, conn: sqlite3.Connection) -> dict[str, str]:
        """Build mapping: chat_identifier -> display_name (for group chats)."""
        cursor = conn.execute("""
            SELECT chat_identifier, display_name
            FROM chat
            WHERE display_name IS NOT NULL AND display_name != ''
        """)
        return {row["chat_identifier"]: row["display_name"] for row in cursor}

    # -- Attachment lookup --

    def _get_message_attachments(
        self, conn: sqlite3.Connection, message_rowids: list[int]
    ) -> dict[int, list[dict]]:
        """Batch-fetch attachment metadata for a set of message ROWIDs."""
        if not message_rowids:
            return {}
        result: dict[int, list[dict]] = {}
        chunk_size = 900
        for i in range(0, len(message_rowids), chunk_size):
            chunk = message_rowids[i:i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            cursor = conn.execute(f"""
                SELECT
                    maj.message_id,
                    a.filename,
                    a.mime_type,
                    a.uti,
                    a.transfer_name,
                    a.total_bytes
                FROM message_attachment_join maj
                JOIN attachment a ON maj.attachment_id = a.ROWID
                WHERE maj.message_id IN ({placeholders})
            """, chunk)
            for row in cursor:
                mid = row["message_id"]
                att_type = _classify_attachment(row["mime_type"], row["uti"], row["filename"])
                result.setdefault(mid, []).append({
                    "type": att_type,
                    "filename": row["transfer_name"] or row["filename"],
                    "mime_type": row["mime_type"],
                    "total_bytes": row["total_bytes"],
                })
        return result

    # -- Main read method --

    def read_since(self, watermark_rowid: int = 0) -> list[TextEvent]:
        """Read all messages since watermark. Returns normalized TextEvents.

        Handles:
        - attributedBody blob parsing (macOS Sequoia format)
        - Phone normalization via phonenumbers library
        - Thread participant lists from chat_handle_join
        - Reactions (associated_message_type 2000-3006)
        - Edits (date_edited > 0)
        - Unsends (date_retracted > 0)
        - Attachment metadata from message_attachment_join
        - URL extraction from message text
        - Thread type detection (1on1 vs group)
        """
        conn = self._connect()

        thread_participants = self._get_thread_participants(conn)
        display_names = self._get_chat_display_names(conn)

        # Fetch messages -- include ALL types (normal + reactions + edits)
        cursor = conn.execute("""
            SELECT
                m.ROWID as row_id,
                m.guid,
                m.text,
                m.attributedBody,
                m.date as timestamp,
                m.is_from_me,
                m.cache_roomnames,
                m.associated_message_type,
                m.associated_message_guid,
                m.cache_has_attachments,
                m.date_edited,
                m.date_retracted,
                m.reply_to_guid,
                m.thread_originator_guid,
                COALESCE(h.id, ch.id) as handle_id,
                COALESCE(h.service, ch.service, 'iMessage') as service,
                cmj.chat_id as chat_rowid
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            LEFT JOIN chat c ON cmj.chat_id = c.ROWID
            LEFT JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
            LEFT JOIN handle ch ON chj.handle_id = ch.ROWID
            WHERE m.ROWID > ? AND m.date >= ?
            GROUP BY m.ROWID
            ORDER BY m.ROWID ASC
        """, (watermark_rowid, TEXT_SYNC_EARLIEST_NANOS))

        # Collect rows first (need ROWIDs for batch attachment lookup)
        raw_rows = list(cursor)
        if not raw_rows:
            return []

        # Batch-fetch attachments for messages that have them
        attachment_rowids = [r["row_id"] for r in raw_rows if r["cache_has_attachments"]]
        attachments_map = self._get_message_attachments(conn, attachment_rowids)

        # Build chat_identifier lookup (chat_rowid -> chat_identifier)
        chat_rowids = {r["chat_rowid"] for r in raw_rows if r["chat_rowid"]}
        chat_id_map: dict[int, str] = {}
        if chat_rowids:
            placeholders = ",".join("?" * len(chat_rowids))
            id_cursor = conn.execute(
                f"SELECT ROWID, chat_identifier FROM chat WHERE ROWID IN ({placeholders})",
                list(chat_rowids),
            )
            chat_id_map = {row["ROWID"]: row["chat_identifier"] for row in id_cursor}

        events: list[TextEvent] = []
        skipped = 0

        for row in raw_rows:
            rowid = row["row_id"]
            assoc_type = row["associated_message_type"] or 0
            is_from_me = bool(row["is_from_me"])
            handle_raw = row["handle_id"]

            # Resolve thread identifier
            chat_rowid = row["chat_rowid"]
            thread_id = chat_id_map.get(chat_rowid) if chat_rowid else None
            if not thread_id:
                thread_id = row["cache_roomnames"] or handle_raw
            if not thread_id:
                skipped += 1
                continue

            # Determine thread type
            is_group = bool(row["cache_roomnames"])
            thread_type = "group" if is_group else "1on1"

            # Resolve sender phone
            sender_phone = None
            if not is_from_me and handle_raw:
                sender_phone = _normalize_phone(handle_raw)
                if not sender_phone and "@" in (handle_raw or ""):
                    sender_phone = handle_raw

            # Skip messages with no identifiable sender/recipient
            if not is_from_me and not sender_phone:
                skipped += 1
                continue

            # Timestamp
            ts = _apple_ts_to_datetime(row["timestamp"])
            if not ts:
                skipped += 1
                continue

            # Determine content_type and content
            content_type = "text"
            content = None
            refers_to = None

            if assoc_type in _REACTION_TYPES:
                content_type = "reaction"
                reaction_name = _REACTION_TYPES[assoc_type]
                content = reaction_name
                assoc_guid = row["associated_message_guid"]
                if assoc_guid:
                    clean_guid = re.sub(r"^[a-z]+:\d+/", "", assoc_guid)
                    clean_guid = re.sub(r"^[a-z]+:", "", clean_guid)
                    refers_to = clean_guid

            elif row["date_retracted"] and row["date_retracted"] > 0:
                content_type = "unsend"
                content = None

            elif row["date_edited"] and row["date_edited"] > 0:
                content_type = "edit"
                content = row["text"]
                if not content and row["attributedBody"]:
                    content = _extract_text_from_attributed_body(row["attributedBody"])

            else:
                content = row["text"]
                if not content and row["attributedBody"]:
                    content = _extract_text_from_attributed_body(row["attributedBody"])
                if not content and row["cache_has_attachments"]:
                    content_type = "attachment"

            # Skip truly empty normal messages
            if content_type == "text" and not content and not row["cache_has_attachments"]:
                skipped += 1
                continue

            # URL detection
            attachment_type = None
            attachment_filename = None
            attachment_url = None

            if content and content_type == "text":
                urls = _URL_PATTERN.findall(content)
                if urls:
                    content_type = "link"
                    attachment_url = urls[0]

            # Attachment metadata
            msg_attachments = attachments_map.get(rowid, [])
            if msg_attachments:
                first_att = msg_attachments[0]
                if content_type in ("text", "attachment"):
                    content_type = "attachment"
                attachment_type = first_att["type"]
                attachment_filename = first_att["filename"]

            # Thread participants
            participants = thread_participants.get(thread_id, [])
            group_name = display_names.get(thread_id)
            direction = "sent" if is_from_me else "received"

            events.append(TextEvent(
                source="imessage",
                source_message_id=str(rowid),
                thread_identifier=thread_id,
                thread_type=thread_type,
                sender_phone=sender_phone,
                sender_name=None,
                direction=direction,
                content=content,
                content_type=content_type,
                timestamp=ts,
                is_group=is_group,
                group_name=group_name,
                participant_phones=participants,
                attachment_type=attachment_type,
                attachment_filename=attachment_filename,
                attachment_url=attachment_url,
                refers_to_message_id=refers_to,
                is_from_me=is_from_me,
                raw_metadata={
                    "guid": row["guid"],
                    "reply_to_guid": row["reply_to_guid"],
                    "thread_originator_guid": row["thread_originator_guid"],
                    "associated_message_type": assoc_type,
                    "service": row["service"],
                } if any([row["reply_to_guid"], row["thread_originator_guid"], assoc_type]) else None,
            ))

        if skipped:
            logger.debug("IMessageAdapter: skipped %d unparseable messages", skipped)
        logger.info("IMessageAdapter: read %d events since ROWID %d", len(events), watermark_rowid)
        return events

    def get_max_rowid(self) -> int:
        """Get current maximum ROWID in the message table."""
        conn = self._connect()
        cursor = conn.execute("SELECT MAX(ROWID) FROM message")
        result = cursor.fetchone()
        return result[0] if result and result[0] else 0

    def get_thread_summary(self) -> dict[str, dict]:
        """Get summary info for all threads (for diagnostics/debugging)."""
        conn = self._connect()
        cursor = conn.execute("""
            SELECT
                c.chat_identifier,
                c.display_name,
                c.style,
                COUNT(DISTINCT cmj.message_id) as msg_count
            FROM chat c
            LEFT JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
            GROUP BY c.ROWID
            ORDER BY msg_count DESC
        """)
        result = {}
        for row in cursor:
            chat_id = row["chat_identifier"]
            result[chat_id] = {
                "display_name": row["display_name"],
                "is_group": row["style"] == 43,
                "message_count": row["msg_count"],
            }
        return result
