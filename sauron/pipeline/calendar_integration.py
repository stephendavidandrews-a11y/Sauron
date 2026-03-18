"""Google Calendar attendee resolution for speaker identification.

Matches conversation timestamps to calendar events and resolves
attendee emails to unified_contacts records.
"""
import json
import logging
import os
from datetime import datetime, timedelta

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


def _get_calendar_attendees(conn, conversation_id: str) -> list[dict]:
    """Match conversation timestamp to Google Calendar events and resolve attendees.

    Returns list of {"matched_contact_id": id, "email": email} or empty list.
    Non-fatal: returns empty list on any failure.
    """
    try:
        conv = conn.execute(
            "SELECT captured_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not conv or not conv["captured_at"]:
            return []

        from datetime import datetime as dt, timedelta
        import os

        captured_at_str = conv["captured_at"]
        try:
            captured_at = dt.fromisoformat(captured_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.debug(f"Could not parse captured_at: {captured_at_str}")
            return []

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            logger.debug("Google API client not available — skipping calendar")
            return []

        token_path = os.environ.get(
            "GOOGLE_CALENDAR_TOKEN",
            os.path.expanduser("~/.config/sauron/calendar_token.json"),
        )
        if not os.path.exists(token_path):
            return []

        import json as _json
        with open(token_path) as f:
            token_data = _json.load(f)
        creds = Credentials.from_authorized_user_info(token_data)

        service = build("calendar", "v3", credentials=creds)

        from sauron.config import GOOGLE_CALENDAR_ID
        time_min = (captured_at - timedelta(minutes=30)).isoformat()
        time_max = (captured_at + timedelta(minutes=30)).isoformat()

        calendar_id = GOOGLE_CALENDAR_ID or "primary"
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        if not events:
            return []

        event = events[0]
        attendees_emails = [
            a.get("email", "") for a in event.get("attendees", [])
            if a.get("email")
        ]

        if not attendees_emails:
            return []

        event_id = event.get("id", "")
        if event_id:
            conn.execute(
                "UPDATE conversations SET calendar_event_id = ? WHERE id = ?",
                (event_id, conversation_id),
            )

        matched = []
        for email in attendees_emails:
            contact = conn.execute(
                "SELECT id FROM unified_contacts WHERE LOWER(email) = LOWER(?)",
                (email,),
            ).fetchone()
            if contact:
                matched.append({
                    "matched_contact_id": contact["id"],
                    "email": email,
                })

        logger.info(
            f"[{conversation_id[:8]}] Calendar: event '{event.get('summary', '?')}' — "
            f"{len(attendees_emails)} attendees, {len(matched)} resolved to contacts"
        )
        return matched

    except Exception as exc:
        logger.warning(f"Calendar attendee lookup failed (non-fatal): {exc}")
        return []
