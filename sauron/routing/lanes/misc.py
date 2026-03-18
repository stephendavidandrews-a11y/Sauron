"""Routing lanes: Standing offers, contact fields, policy positions, resources.

Extracted from sauron/routing/networking.py (Phase 8 decomposition).
Lanes 3, 5, 10, 11.
"""

import logging

from sauron.config import NETWORKING_APP_URL
from sauron.routing.lanes import core as _core
from sauron.routing.lanes.core import RoutingContext
from sauron.routing.lanes.entity_resolution import (
    _resolve_contact_id_for_entity, _resolve_with_synthesis_links,
    _SKIP_SENTINEL,
)
from sauron.routing.lanes.commitments import _update_contact_field_null_only

logger = logging.getLogger(__name__)


def route_standing_offers(ctx: RoutingContext):
    """Lane 3: Standing offers (Phase 4: prefer synthesis_entity_links)."""
    for idx, offer in enumerate(ctx.synthesis.get("standing_offers", [])):
        offer_cid = _resolve_with_synthesis_links(
            ctx.sel_conn, ctx.conversation_id, "standing_offer", idx, "contact_name",
            offer.get("contact_name", ""), ctx.networking_app_contact_id,
        )
        if offer_cid == _SKIP_SENTINEL:
            logger.debug(f"Skipping standing_offer[{idx}]: person marked as skipped")
            continue
        if not offer_cid:
            logger.debug(f"Skipping standing_offer[{idx}]: could not resolve contact")
            continue
        offer_payload = {
            "contactId": offer_cid,
            "contactName": offer.get("contact_name", ""),
            "description": offer.get("description", ""),
            "offeredBy": offer.get("offered_by", "them"),
            "originalWords": offer.get("original_words", ""),
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": offer.get("source_claim_id"),
        }
        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/standing-offers", offer_payload
        )
        if ok:
            ctx.successes.append(("standing_offer", offer_payload))
        else:
            ctx.errors.append(("standing_offer", offer_payload, err))


def route_contact_field_updates(ctx: RoutingContext):
    """Lane 5: Contact field updates - null-only patching (Phase C)."""
    for mw in ctx.claims.get("memory_writes", []):
        if mw.get("entity_type") != "person":
            continue
        if mw.get("field") in ("interest", "activity", "lifeEvent"):
            continue
        field_ok, field_err = _update_contact_field_null_only(
            mw, ctx.networking_app_contact_id
        )
        if field_ok is not None:  # None = skipped (already has value)
            if field_ok:
                ctx.successes.append(("contact_update", mw))
            else:
                ctx.errors.append(("contact_update", mw, field_err))


def route_policy_positions(ctx: RoutingContext):
    """Lane 10: Intelligence signals from policy positions."""
    for pp in ctx.synthesis.get("policy_positions", []):
        person_name = pp.get("person", "")
        pp_contact_id = _resolve_contact_id_for_entity(
            person_name, ctx.networking_app_contact_id
        )
        if not pp_contact_id:
            continue
        sig_payload = {
            "contactId": pp_contact_id,
            "signalType": "policy_position",
            "title": f"{person_name}: {pp.get('topic', 'unknown topic')}",
            "description": pp.get("position", ""),
            "sourceName": "sauron",
            "relevanceScore": pp.get("strength", 0.5) * 10,
            "outreachHook": pp.get("notes") or None,
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": pp.get("claim_id"),
        }
        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/signals", sig_payload
        )
        if ok:
            ctx.successes.append(("intelligence_signal", sig_payload))
        else:
            ctx.secondary_errors.append(("intelligence_signal", sig_payload, err))


def route_referenced_resources(ctx: RoutingContext):
    """Lane 11: Referenced resources."""
    for res in ctx.synthesis.get("referenced_resources", []):
        res_contact_id = _resolve_contact_id_for_entity(
            res.get("contact_name", ""), ctx.networking_app_contact_id
        )
        if not res_contact_id:
            logger.debug(f"Skipping referenced_resource: could not resolve contact")
            continue
        res_payload = {
            "contactId": res_contact_id,
            "description": res.get("description", ""),
            "resourceType": res.get("resource_type", "other"),
            "url": res.get("url"),
            "action": res.get("action", "reference_only"),
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": res.get("source_claim_id"),
        }
        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/referenced-resources", res_payload
        )
        if ok:
            ctx.successes.append(("referenced_resource", res_payload))
        else:
            ctx.secondary_errors.append(("referenced_resource", res_payload, err))
