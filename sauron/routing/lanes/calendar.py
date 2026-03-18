"""Routing lane: Calendar events.

Extracted from sauron/routing/networking.py (Phase 8 decomposition).
Lane 16.
"""

import logging

from sauron.config import NETWORKING_APP_URL
from sauron.routing.lanes import core as _core
from sauron.routing.lanes.core import RoutingContext

logger = logging.getLogger(__name__)


def route_calendar_events(ctx: RoutingContext):
    """Lane 16: Route calendar_events to Networking's Google Calendar integration.

    Attendee names are included in description/context rather than
    blocking event creation on unresolved contacts.
    """
    for cal_event in ctx.synthesis.get("calendar_events", []):
        title = cal_event.get("title", "")
        if not title:
            continue
        suggested_date = cal_event.get("suggested_date")
        start_time = cal_event.get("start_time", "")
        end_time = cal_event.get("end_time", "")
        location = cal_event.get("location", "")
        original_words = cal_event.get("original_words", "")
        is_placeholder = cal_event.get("is_placeholder", False)
        attendees = cal_event.get("attendees", [])

        # Build description
        desc_parts = [f"Source: Sauron conversation {ctx.conversation_id[:8]}"]
        if attendees:
            desc_parts.append(f"Mentioned attendees: {', '.join(attendees)}")
        if original_words:
            desc_parts.append(f'Original words: "{original_words}"')

        cal_payload = {
            "summary": title,
            "sourceSystem": "sauron",
            "sourceId": str(ctx.conversation_id),
            "sourceClaimId": cal_event.get("source_claim_id") or f"cal:{title[:60]}",
        }

        if start_time:
            cal_payload["start"] = start_time
            cal_payload["end"] = end_time or start_time
            if is_placeholder:
                desc_parts.append(
                    "Note: Time is an inferred placeholder, not explicitly stated."
                )
        elif suggested_date:
            cal_payload["start"] = f"{suggested_date}T09:00:00-05:00"
            cal_payload["end"] = f"{suggested_date}T10:00:00-05:00"
            desc_parts.append(
                "Time placeholder inferred by Sauron; "
                "original extraction only provided a date."
            )
        else:
            logger.debug(
                f"Skipping calendar_event '{title}': no date or time available"
            )
            continue

        cal_payload["description"] = "\n".join(desc_parts)

        if location:
            cal_payload["location"] = location

        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/calendar/events", cal_payload
        )
        if ok:
            ctx.successes.append(("calendar_event", cal_payload))
        else:
            ctx.secondary_errors.append(("calendar_event", cal_payload, err))
