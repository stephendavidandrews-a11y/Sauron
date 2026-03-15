"""Text cluster preprocessor — format messages for Claude extraction.

Converts a cluster's messages into a structured transcript format
that Claude can extract claims from. This is the text equivalent of
the diarized transcript used for voice conversations.

OUTPUT FORMAT:
    [2026-03-13 09:14] STEPHEN: Hey, did you get a chance to look at the draft?
    [2026-03-13 09:17] SARAH CHEN: Yeah I read it last night. I think the requirements are too aggressive
    [2026-03-13 09:17] SARAH CHEN: Especially section 4.3
    [2026-03-13 09:19] STEPHEN: Interesting. Heath said the same thing yesterday
    [2026-03-13 09:21] SARAH CHEN: I'll write up my thoughts and send them to you by Friday
    [2026-03-13 09:22] STEPHEN: 👍 [reaction to line 5]
    [2026-03-13 10:45] SARAH CHEN: [shared link: https://cftc.gov/draft-4.3.pdf]

Evidence spans reference LINE NUMBERS (1-indexed), not timestamps.
Each message has a stable ordinal from text_cluster_messages.
"""

import logging
import sqlite3
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/New_York")

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)


def _get_conn(db_path=None) -> sqlite3.Connection:
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def format_cluster_for_extraction(
    cluster_id: str,
    phone_index: dict | None = None,
    db_path=None,
) -> dict:
    """Format a cluster's messages into a structured transcript for Claude.

    Args:
        cluster_id: text_clusters.id
        phone_index: dict[phone, {contact_id, name}] from identity.build_phone_index()
        db_path: optional DB path override

    Returns:
        dict with:
            transcript: formatted text for Claude
            metadata: cluster info (thread_type, participant_count, etc.)
            line_count: number of lines in transcript
            message_count: number of messages
            total_chars: total character count of content
            participant_names: list of resolved names
            participant_map: dict[phone, name] for roster
    """
    conn = _get_conn(db_path)
    try:
        # Get cluster info
        cluster = conn.execute(
            """SELECT tc.id, tc.thread_id, tc.start_time, tc.end_time,
                      tc.message_count, tc.participant_count, tc.depth_lane,
                      tt.thread_type, tt.display_name, tt.thread_identifier,
                      tt.participant_phones
               FROM text_clusters tc
               JOIN text_threads tt ON tc.thread_id = tt.id
               WHERE tc.id = ?""",
            (cluster_id,),
        ).fetchone()

        if not cluster:
            logger.warning("Cluster %s not found", cluster_id)
            return {"transcript": "", "metadata": {}, "line_count": 0,
                    "message_count": 0, "total_chars": 0,
                    "participant_names": [], "participant_map": {}}

        # Get messages in order via text_cluster_messages
        messages = conn.execute(
            """SELECT tm.id, tm.source_message_id, tm.sender_phone,
                      tm.sender_contact_id, tm.direction, tm.content,
                      tm.content_type, tm.timestamp, tm.is_from_me,
                      tm.attachment_type, tm.attachment_filename,
                      tm.attachment_url, tm.refers_to_message_id,
                      tcm.ordinal
               FROM text_cluster_messages tcm
               JOIN text_messages tm ON tcm.message_id = tm.id
               WHERE tcm.cluster_id = ?
               ORDER BY tcm.ordinal ASC""",
            (cluster_id,),
        ).fetchall()

        if not messages:
            # Fallback: get messages by time range from thread
            messages = conn.execute(
                """SELECT id, source_message_id, sender_phone,
                          sender_contact_id, direction, content,
                          content_type, timestamp, is_from_me,
                          attachment_type, attachment_filename,
                          attachment_url, refers_to_message_id,
                          0 as ordinal
                   FROM text_messages
                   WHERE thread_id = ?
                     AND timestamp >= ? AND timestamp <= ?
                   ORDER BY timestamp ASC""",
                (cluster["thread_id"], cluster["start_time"], cluster["end_time"]),
            ).fetchall()

        # Build phone → name mapping
        import json as _json
        participant_phones = []
        try:
            participant_phones = _json.loads(cluster["participant_phones"] or "[]")
        except (ValueError, TypeError):
            pass

        phone_to_name = {}
        if phone_index:
            for phone in participant_phones:
                info = phone_index.get(phone)
                if info:
                    phone_to_name[phone] = info["name"]

        # Also resolve sender_contact_id to names
        contact_ids = set()
        for m in messages:
            if m["sender_contact_id"]:
                contact_ids.add(m["sender_contact_id"])

        contact_id_to_name = {}
        if contact_ids:
            placeholders = ",".join("?" * len(contact_ids))
            contacts = conn.execute(
                f"SELECT id, canonical_name FROM unified_contacts WHERE id IN ({placeholders})",
                list(contact_ids),
            ).fetchall()
            for c in contacts:
                contact_id_to_name[c["id"]] = c["canonical_name"]

        # Build message-id lookup for reaction references
        msg_id_to_line = {}  # source_message_id → line number
        msg_id_to_content = {}  # source_message_id → message content text

        # Format messages
        lines = []
        total_chars = 0
        participant_names_seen = set()

        for msg in messages:
            line_num = len(lines) + 1

            # Track message ID → line number and content for reactions
            if msg["source_message_id"]:
                msg_id_to_line[msg["source_message_id"]] = line_num
                if msg["content_type"] in ("text", "link") and msg["content"]:
                    msg_id_to_content[msg["source_message_id"]] = msg["content"].strip()

            # Resolve sender name
            sender_name = _resolve_sender(
                msg, phone_to_name, contact_id_to_name
            )
            participant_names_seen.add(sender_name)

            # Format timestamp
            ts_str = _format_timestamp(msg["timestamp"])

            # Format content based on type
            content = _format_content(
                msg, msg_id_to_line, line_num, msg_id_to_content
            )

            total_chars += len(content)
            lines.append(f"[{ts_str}] {sender_name}: {content}")

        transcript = "\n".join(lines)

        # Build participant map for roster injection
        participant_map = {}
        for phone, name in phone_to_name.items():
            participant_map[phone] = name
        # Add self
        participant_map["self"] = "Stephen Andrews"

        metadata = {
            "cluster_id": cluster["id"],
            "thread_id": cluster["thread_id"],
            "thread_type": cluster["thread_type"],
            "display_name": cluster["display_name"],
            "thread_identifier": cluster["thread_identifier"],
            "start_time": cluster["start_time"],
            "end_time": cluster["end_time"],
            "message_count": cluster["message_count"],
            "participant_count": cluster["participant_count"],
            "depth_lane": cluster["depth_lane"],
        }

        return {
            "transcript": transcript,
            "metadata": metadata,
            "line_count": len(lines),
            "message_count": len(messages),
            "total_chars": total_chars,
            "participant_names": sorted(participant_names_seen),
            "participant_map": participant_map,
        }

    finally:
        conn.close()


def _resolve_sender(msg, phone_to_name: dict, contact_id_to_name: dict) -> str:
    """Resolve a message sender to a display name."""
    # Self (sent messages)
    if msg["is_from_me"] or msg["direction"] == "sent":
        return "STEPHEN"

    # Try contact_id first (most reliable)
    if msg["sender_contact_id"] and msg["sender_contact_id"] in contact_id_to_name:
        name = contact_id_to_name[msg["sender_contact_id"]]
        return name.upper()

    # Try phone → name
    if msg["sender_phone"] and msg["sender_phone"] in phone_to_name:
        name = phone_to_name[msg["sender_phone"]]
        return name.upper()

    # Fallback to phone number
    if msg["sender_phone"]:
        return msg["sender_phone"]

    return "UNKNOWN"


def _format_timestamp(ts_str: str) -> str:
    """Format ISO timestamp to compact display format in Eastern time."""
    if not ts_str:
        return "??:??"
    try:
        if isinstance(ts_str, datetime):
            dt = ts_str
        else:
            ts_str = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str)
        # Convert to Eastern timezone for display
        if dt.tzinfo is not None:
            dt = dt.astimezone(LOCAL_TZ)
        return dt.strftime("%m/%d %H:%M")
    except (ValueError, TypeError):
        return ts_str[:16] if len(ts_str) >= 16 else ts_str


def _format_content(msg, msg_id_to_line: dict, current_line: int, msg_id_to_content: dict | None = None) -> str:
    """Format message content based on content_type."""
    content_type = msg["content_type"] or "text"
    content = msg["content"] or ""

    if content_type == "text":
        return content.strip() if content else "[empty message]"

    elif content_type == "reaction":
        # Render reaction with reference to which message AND its content
        ref_id = msg["refers_to_message_id"]
        ref_line = msg_id_to_line.get(ref_id)
        reaction_text = content.strip() if content else "reacted"
        if ref_line and msg_id_to_content:
            ref_content = msg_id_to_content.get(ref_id, "")
            if ref_content:
                # Truncate long messages for readability
                preview = ref_content[:80]
                if len(ref_content) > 80:
                    preview += "..."
                return f'{reaction_text} [reaction to line {ref_line}: "{preview}"]'
            return f"{reaction_text} [reaction to line {ref_line}]"
        elif ref_line:
            return f"{reaction_text} [reaction to line {ref_line}]"
        return f"{reaction_text} [reaction]"

    elif content_type == "attachment":
        att_type = msg["attachment_type"] or "file"
        filename = msg["attachment_filename"] or ""
        if filename:
            return f"[shared {att_type}: {filename}]"
        return f"[shared {att_type}]"

    elif content_type == "link":
        url = msg["attachment_url"] or ""
        if url:
            label = content.strip() if content else "link"
            return f"[shared link: {url}]" if label == "link" else f"{label} [link: {url}]"
        return content.strip() if content else "[shared link]"

    elif content_type == "edit":
        return f"[message edited] {content.strip()}" if content else "[message edited]"

    elif content_type == "unsend":
        return "[message unsent]"

    else:
        return content.strip() if content else f"[{content_type}]"


def build_text_participant_roster(
    participant_map: dict,
    db_path=None,
) -> str:
    """Build a participant roster for text extraction prompts.

    Similar to _build_participant_roster in claims.py but uses text-specific
    participant resolution (phone → contact) instead of speaker label mapping.

    Args:
        participant_map: dict[phone, name] from format_cluster_for_extraction
        db_path: optional DB path override

    Returns:
        Formatted roster string for prompt injection.
    """
    if not participant_map:
        return ""

    conn = _get_conn(db_path)
    try:
        lines = []
        lines.append("## Participant Roster")
        lines.append("The following people are participating in this text conversation:")
        lines.append("")

        first_names_seen = {}

        for identifier, name in sorted(participant_map.items()):
            if identifier == "self":
                lines.append(f"- STEPHEN → **Stephen Andrews** (the system owner)")
                first_names_seen.setdefault("Stephen", []).append("Stephen Andrews")
                continue

            # Look up contact details
            contact = conn.execute(
                "SELECT id, canonical_name, aliases, relationships FROM unified_contacts WHERE canonical_name = ?",
                (name,),
            ).fetchone()

            full_name = name
            first_name = full_name.split()[0] if full_name else identifier
            first_names_seen.setdefault(first_name, []).append(full_name)

            entry = f"- {full_name.upper()} → **{full_name}**"

            if contact:
                aliases = contact["aliases"] or ""
                if aliases:
                    alias_list = [a.strip() for a in aliases.split(";") if a.strip()]
                    if alias_list:
                        entry += f" (also known as: {', '.join(alias_list)})"
                lines.append(entry)

                # Relationship context
                import json
                rels_json = contact["relationships"]
                if rels_json:
                    try:
                        rels = json.loads(rels_json)
                    except (json.JSONDecodeError, TypeError):
                        rels = {}

                    context_parts = []
                    rel = rels.get("relation_to_stephen") or rels.get("relationship")
                    if rel:
                        context_parts.append(f"Relationship to Stephen: {rel}")
                    group = rels.get("personal_group")
                    if group:
                        context_parts.append(f"Group: {group}")
                    if context_parts:
                        lines.append(f"  Context: {'; '.join(context_parts)}")
            else:
                lines.append(entry)

        # Disambiguation warnings
        ambiguous = {fn: names for fn, names in first_names_seen.items() if len(names) > 1}
        if ambiguous:
            lines.append("")
            lines.append("⚠️ NAME DISAMBIGUATION REQUIRED:")
            for first_name, full_names in ambiguous.items():
                names_str = " and ".join(f'"{n}"' for n in full_names)
                lines.append(
                    f"  Multiple people named \"{first_name}\": {names_str}. "
                    f"Use FULL NAMES for ALL references."
                )

        lines.append("")
        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to build text participant roster: %s", e)
        return ""
    finally:
        conn.close()
