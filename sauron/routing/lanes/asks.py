"""Routing lane: Asks (soft commitments).

Extracted from sauron/routing/networking.py (Phase 8 decomposition).
Lane 17.
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


def route_asks(ctx: RoutingContext):
    """Lane 17: Route asks as soft_ask commitments."""
    _asks_list = ctx.synthesis.get("asks", [])
    logger.info(f"Lane 17 asks: {len(_asks_list)} items found in synthesis")
    for idx, ask in enumerate(_asks_list):
        contact_name = ask.get("contact_name", "") or ask.get("asked_of", "")
        if not contact_name:
            ask_cid = ctx.networking_app_contact_id
        elif ctx.sel_conn is not None:
            ask_cid = _resolve_with_synthesis_links(
                ctx.sel_conn, ctx.conversation_id, "ask", idx,
                "contact_name", contact_name, ctx.networking_app_contact_id,
            )
            if ask_cid == _SKIP_SENTINEL:
                logger.debug(f"Skipping ask[{idx}]: person marked as skipped")
                continue
        else:
            ask_cid = _resolve_contact_id_for_entity(
                contact_name, ctx.networking_app_contact_id
            )

        if not ask_cid:
            logger.debug(f"Skipping ask[{idx}]: could not resolve '{contact_name}'")
            continue

        # Map ask direction to commitment direction
        asked_by = ask.get("asked_by", "")
        if asked_by.lower() in ("me", "i", "stephen"):
            ask_direction = "they_owe"
        else:
            ask_direction = "i_owe"

        ask_payload = {
            "contactId": ask_cid,
            "description": ask.get("description", ""),
            "direction": ask_direction,
            "kind": "soft_ask",
            "firmness": "tentative" if ask.get("ask_type") == "soft_ask" else "intentional",
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": ask.get("source_claim_id"),
        }

        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/commitments", ask_payload
        )
        if ok:
            ctx.successes.append(("ask_commitment", ask_payload))
        else:
            ctx.secondary_errors.append(("ask_commitment", ask_payload, err))
