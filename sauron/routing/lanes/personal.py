"""Routing lanes: Life events, interests, activities.

Extracted from sauron/routing/networking.py (Phase 8 decomposition).
Lanes 6, 7, 8, 18.
"""

import logging

from sauron.config import NETWORKING_APP_URL
from sauron.routing.lanes import core as _core
from sauron.routing.lanes.core import RoutingContext
from sauron.routing.lanes.entity_resolution import (
    _resolve_contact_id_for_entity, _resolve_with_synthesis_links,
    _SKIP_SENTINEL,
)

logger = logging.getLogger(__name__)


def route_life_events_from_claims(ctx: RoutingContext):
    """Lane 6: Life events from claims memory_writes."""
    for mw in ctx.claims.get("memory_writes", []):
        if mw.get("field") != "lifeEvent" or not mw.get("entity_name"):
            continue
        contact_id = _resolve_contact_id_for_entity(
            mw.get("entity_name", ""), ctx.networking_app_contact_id
        )
        if not contact_id:
            continue
        le_payload = {
            "description": mw.get("value", ""),
            "person": mw.get("entity_name", "unknown"),
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": mw.get("claim_id"),
        }
        ok, err, _resp = _core._api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/contacts/{contact_id}/life-events",
            le_payload,
        )
        if ok:
            ctx.successes.append(("life_event", le_payload))
        else:
            ctx.errors.append(("life_event", le_payload, err))


def route_interests(ctx: RoutingContext):
    """Lane 7: Personal interests from claims memory_writes."""
    for mw in ctx.claims.get("memory_writes", []):
        if mw.get("field") != "interest":
            continue
        contact_id = _resolve_contact_id_for_entity(
            mw.get("entity_name", ""), ctx.networking_app_contact_id
        )
        if not contact_id:
            continue
        int_payload = {
            "contactId": contact_id,
            "interest": mw.get("value", ""),
            "source": "sauron",
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": mw.get("claim_id"),
        }
        ok, err, _resp = _core._api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/personal/interests",
            int_payload,
        )
        if ok:
            ctx.successes.append(("interest", int_payload))
        else:
            ctx.secondary_errors.append(("interest", int_payload, err))


def route_activities(ctx: RoutingContext):
    """Lane 8: Personal activities from claims memory_writes."""
    for mw in ctx.claims.get("memory_writes", []):
        if mw.get("field") != "activity":
            continue
        contact_id = _resolve_contact_id_for_entity(
            mw.get("entity_name", ""), ctx.networking_app_contact_id
        )
        if not contact_id:
            continue
        act_payload = {
            "contactId": contact_id,
            "activity": mw.get("value", ""),
            "source": "sauron",
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": mw.get("claim_id"),
        }
        ok, err, _resp = _core._api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/personal/activities",
            act_payload,
        )
        if ok:
            ctx.successes.append(("activity", act_payload))
        else:
            ctx.secondary_errors.append(("activity", act_payload, err))


def route_life_events_from_synthesis(ctx: RoutingContext):
    """Lane 18: Life events from synthesis (complements Lane 6 claims)."""
    _le_list = ctx.synthesis.get("life_events", [])
    logger.info(f"Lane 18 life_events: {len(_le_list)} items found in synthesis")
    for idx, le in enumerate(_le_list):
        contact_name = le.get("contact_name", "")
        if not contact_name:
            le_cid = ctx.networking_app_contact_id
        elif ctx.sel_conn is not None:
            le_cid = _resolve_with_synthesis_links(
                ctx.sel_conn, ctx.conversation_id, "life_event", idx,
                "contact_name", contact_name, ctx.networking_app_contact_id,
            )
            if le_cid == _SKIP_SENTINEL:
                logger.debug(f"Skipping life_event[{idx}]: person marked as skipped")
                continue
        else:
            le_cid = _resolve_contact_id_for_entity(
                contact_name, ctx.networking_app_contact_id
            )

        if not le_cid:
            logger.debug(f"Skipping life_event[{idx}]: could not resolve '{contact_name}'")
            continue

        le_payload = {
            "description": le.get("description", ""),
            "person": contact_name or "unknown",
            "eventType": le.get("event_type", "custom"),
            "eventDate": le.get("approximate_date"),
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": le.get("source_claim_id"),
        }

        ok, err, _resp = _core._api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/contacts/{le_cid}/life-events",
            le_payload,
        )
        if ok:
            ctx.successes.append(("synthesis_life_event", le_payload))
        else:
            ctx.secondary_errors.append(("synthesis_life_event", le_payload, err))
