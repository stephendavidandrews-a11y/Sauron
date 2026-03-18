"""Routing lane: Graph edges → ContactRelationship.

Extracted from sauron/routing/networking.py (Phase 8 decomposition).
Lane 9.
"""

import logging
import re as _re

from sauron.config import NETWORKING_APP_URL
from sauron.routing.lanes import core as _core
from sauron.routing.lanes.core import RoutingContext
from sauron.routing.lanes.entity_resolution import (
    _resolve_with_synthesis_links, _find_provisional_entity_id,
    _hold_pending_route, _SKIP_SENTINEL,
)

logger = logging.getLogger(__name__)

_UUID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def route_graph_edges(ctx: RoutingContext):
    """Lane 9: Route graph_edges to /api/contact-relationships.

    Phase 4: prefers synthesis_entity_links for contact resolution.
    Skips self-referential edges and non-UUID contact IDs.
    """
    for idx, edge in enumerate(ctx.synthesis.get("graph_edges", [])):
        from_name = edge.get("from_entity", "")
        to_name = edge.get("to_entity", "")
        if not from_name or not to_name:
            continue

        # Phase 4: Resolve via synthesis_entity_links first, fallback to name-string
        from_cid = _resolve_with_synthesis_links(
            ctx.sel_conn, ctx.conversation_id, "graph_edge", idx, "from_entity",
            from_name, None,
        )
        to_cid = _resolve_with_synthesis_links(
            ctx.sel_conn, ctx.conversation_id, "graph_edge", idx, "to_entity",
            to_name, None,
        )

        # Skip if either side is skipped by user
        if from_cid == _SKIP_SENTINEL or to_cid == _SKIP_SENTINEL:
            logger.debug(
                f"Skipping graph_edge[{idx}] {from_name} -> {to_name}: "
                f"person marked as skipped"
            )
            continue

        if not from_cid or not to_cid:
            # Check if entities are provisional (unresolved) - hold for replay
            blocked_entity = None
            if not from_cid:
                blocked_entity = _find_provisional_entity_id(ctx.sel_conn, from_name)
            elif not to_cid:
                blocked_entity = _find_provisional_entity_id(ctx.sel_conn, to_name)

            if blocked_entity:
                _hold_pending_route(
                    ctx.sel_conn, ctx.conversation_id, "graph_edge",
                    {
                        "from_name": from_name,
                        "to_name": to_name,
                        "from_cid": from_cid,
                        "to_cid": to_cid,
                        "edge_type": edge.get("edge_type", "knows"),
                        "strength": edge.get("strength", 0.5),
                        "sourceSystem": "sauron",
                        "sourceId": ctx.conversation_id,
                    },
                    blocked_entity,
                )
                logger.info(
                    f"Held graph_edge {from_name} -> {to_name}: "
                    f"blocked on entity {blocked_entity[:8]}"
                )
            else:
                logger.debug(
                    f"Skipping edge {from_name} -> {to_name}: "
                    f"unresolved entity (from={from_cid}, to={to_cid})"
                )
            continue

        # Skip self-referential edges
        if from_cid == to_cid:
            logger.debug(
                f"Skipping self-referential edge {from_name} -> {to_name} "
                f"(both resolve to {from_cid[:8]})"
            )
            continue

        # Skip edges where resolved IDs aren't valid UUIDs
        if not _UUID_RE.match(from_cid) or not _UUID_RE.match(to_cid):
            logger.debug(
                f"Skipping graph_edge[{idx}] {from_name} -> {to_name}: "
                f"non-UUID contact ID (from={from_cid[:16]}, to={to_cid[:16]})"
            )
            continue

        pair = sorted([from_name, to_name])
        edge_payload = {
            "contactAId": from_cid,
            "contactBId": to_cid,
            "relationshipType": edge.get("edge_type", "knows"),
            "strength": int(edge.get("strength", 0.5) * 5) + 1,  # 0-1 float -> 1-6 int
            "source": "sauron",
            "observationSource": f"Conversation {ctx.conversation_id[:8]}",
            "sourceSystem": "sauron",
            "sourceId": ctx.conversation_id,
            "sourceClaimId": f"{pair[0]}:{pair[1]}:{edge.get('edge_type', 'knows')}",
        }
        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/contact-relationships", edge_payload
        )
        if ok:
            ctx.successes.append(("contact_relationship", edge_payload))
        else:
            ctx.errors.append(("contact_relationship", edge_payload, err))
