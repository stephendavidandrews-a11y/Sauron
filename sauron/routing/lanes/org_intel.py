"""Routing lanes: Status changes and org intelligence.

Extracted from sauron/routing/networking.py (Phase 8 decomposition).
Lanes 10b, 10c.
"""

import logging

from sauron.config import NETWORKING_APP_URL
from sauron.routing.lanes import core as _core
from sauron.routing.lanes.core import RoutingContext
from sauron.routing.lanes.entity_resolution import (
    _resolve_contact_id_for_entity, _resolve_with_synthesis_links,
    _SKIP_SENTINEL,
)
from sauron.routing.provisional import store_provisional_org

logger = logging.getLogger(__name__)


def route_status_changes(ctx: RoutingContext):
    """Lane 10b: Status changes (secondary, non-fatal)."""
    _sc_list = ctx.synthesis.get("status_changes", [])
    logger.info(f"Lane 10b status_changes: {len(_sc_list)} items found in synthesis")
    for idx, sc in enumerate(_sc_list):
        contact_name = sc.get("contact_name", "")
        if not contact_name:
            continue

        if ctx.sel_conn is not None:
            sc_contact_id = _resolve_with_synthesis_links(
                ctx.sel_conn, ctx.conversation_id, "status_change", idx,
                "contact_name", contact_name, ctx.networking_app_contact_id,
            )
            if sc_contact_id == _SKIP_SENTINEL:
                logger.debug(f"Skipping status_change[{idx}]: person marked as skipped")
                continue
        else:
            sc_contact_id = _resolve_contact_id_for_entity(
                contact_name, ctx.networking_app_contact_id
            )

        if not sc_contact_id:
            logger.debug(f"Skipping status_change[{idx}]: could not resolve '{contact_name}'")
            continue

        # Build description with from/to state context
        _sc_details = sc.get("details", "")
        _sc_from = sc.get("from_state", "")
        _sc_to = sc.get("to_state", "")
        if _sc_from or _sc_to:
            _transition_parts = []
            if _sc_from:
                _transition_parts.append(f"From: {_sc_from}")
            if _sc_to:
                _transition_parts.append(f"To: {_sc_to}")
            _transition_line = " \u2192 ".join(_transition_parts)
            _sc_details = f"{_transition_line}\n{_sc_details}" if _sc_details else _transition_line

        sc_payload = {
            "contactId": sc_contact_id,
            "signalType": "status_change",
            "title": f"{contact_name}: {sc.get('change_type', 'update')}",
            "description": _sc_details,
            "sourceName": "sauron",
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": sc.get("source_claim_id"),
        }
        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/signals", sc_payload
        )
        if ok:
            ctx.successes.append(("status_change_signal", sc_payload))
        else:
            ctx.secondary_errors.append(("status_change_signal", sc_payload, err))


def route_org_intelligence(ctx: RoutingContext):
    """Lane 10c: Org intelligence (secondary, non-fatal).

    Routes to /api/organization-signals. Captures provisional org on 422.
    """
    _oi_list = ctx.synthesis.get("org_intelligence", [])
    logger.info(f"Lane 10c org_intelligence: {len(_oi_list)} items found in synthesis")
    for idx, oi in enumerate(_oi_list):
        org_name = oi.get("organization", "")
        if not org_name:
            continue

        oi_description = oi.get("details", "")
        if oi.get("intel_type") == "org_relationship" and oi.get("related_org"):
            oi_description = (
                f"{oi.get('details', '')} "
                f"[related_org={oi.get('related_org')}, "
                f"relationship_type={oi.get('relationship_type', 'unknown')}]"
            ).strip()

        oi_payload = {
            "organizationName": org_name,
            "signalType": oi.get("intel_type", "intelligence"),
            "title": f"{org_name}: {oi.get('intel_type', 'intelligence')}",
            "description": oi_description,
            "industry": oi.get("industry"),
            "relatedOrg": oi.get("related_org"),
            "relationshipType": oi.get("relationship_type"),
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": oi.get("source_claim_id"),
        }
        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/organization-signals", oi_payload
        )
        if ok:
            ctx.successes.append(("org_intel_signal", oi_payload))
        else:
            if _resp and _resp.get("resolutionSource") == "provisional_suggestion":
                store_provisional_org(
                    raw_name=org_name,
                    normalized_name=org_name.lower().strip(),
                    conversation_id=ctx.conversation_id,
                    source_context=f"org_intelligence: {oi.get('intel_type', '')} - {oi.get('details', '')[:200]}",
                    resolution_source_context="provisional_suggestion",
                    suggested_by="org_intelligence",
                )
            elif err and "422" in err and "not resolved" in err.lower():
                store_provisional_org(
                    raw_name=org_name,
                    normalized_name=org_name.lower().strip(),
                    conversation_id=ctx.conversation_id,
                    source_context=f"org_intelligence: {oi.get('intel_type', '')} - {oi.get('details', '')[:200]}",
                    resolution_source_context=err[:200],
                    suggested_by="org_intelligence",
                )
            ctx.secondary_errors.append(("org_intel_signal", oi_payload, err))
