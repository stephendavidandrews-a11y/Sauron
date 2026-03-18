"""Routing lanes: Interaction creation, participants, and status advance.

Extracted from sauron/routing/networking.py (Phase 8 decomposition).
Lanes 1, 1A, 1C.
"""

import logging
from datetime import datetime, timezone

from sauron.config import NETWORKING_APP_URL
from sauron.routing.lanes import core as _core
from sauron.routing.lanes.core import RoutingContext
from sauron.routing.lanes.signals import _infer_sentiment, _infer_delta
from sauron.routing.lanes.commitments import (
    _collect_inline_commitments, _route_interaction_participants,
)

logger = logging.getLogger(__name__)


def route_interaction(ctx: RoutingContext) -> str | None:
    """Lane 1: Create interaction with inline commitments + follow-ups.

    Returns the created interaction ID (or None if skipped/failed).
    Solo gating: prep skips interaction; debrief skips if summary < 30 chars.
    """
    synthesis = ctx.synthesis
    _skip_interaction = False

    if ctx.is_solo:
        if ctx.solo_mode == "prep":
            _skip_interaction = True
            logger.info("Solo prep: skipping interaction creation (not a past event)")
        elif ctx.solo_mode == "debrief":
            _summary = synthesis.get("summary", "")
            if len(_summary) < 30:
                _skip_interaction = True
                logger.info(
                    f"Solo debrief: skipping interaction (summary too thin: "
                    f"{len(_summary)} chars)"
                )

    if _skip_interaction:
        ctx.core_lane_results.append({"name": "interaction", "status": "skipped_solo"})
        return None

    commitments_inline = _collect_inline_commitments(synthesis)
    follow_ups = synthesis.get("follow_ups", [])
    interaction_payload = {
        "source": "sauron",
        "sourceSystem": "sauron",
        "sourceId": ctx.conversation_id,
        "type": "conversation",
        "date": datetime.now(timezone.utc).isoformat() + "Z",
        "summary": synthesis.get("summary", ""),
        "topicsDiscussed": synthesis.get("topics_discussed", []),
        "relationshipNotes": synthesis.get("relationship_notes"),
        "sentiment": _infer_sentiment(synthesis),
        "relationshipDelta": _infer_delta(synthesis),
        "commitments": commitments_inline,
        "followUpRequired": len(follow_ups) > 0,
        "followUpDescription": "; ".join(
            fu.get("description", "") for fu in follow_ups
        ) if follow_ups else None,
    }
    if ctx.networking_app_contact_id:
        interaction_payload["contactId"] = ctx.networking_app_contact_id

    if not ctx.networking_app_contact_id and not ctx.is_solo:
        logger.info(
            f"Skipping interaction for {ctx.conversation_id[:8]}: "
            f"no primary contact resolved (text conversation without "
            f"identifiable non-Stephen speaker)"
        )
        ctx.core_lane_results.append({"name": "interaction", "status": "skipped_no_contact"})
        return None

    ok, err, _resp = _core._api_call("POST", f"{NETWORKING_APP_URL}/api/interactions", interaction_payload)
    if ok:
        _created_id = _resp.get("id") if isinstance(_resp, dict) else None
        ctx.successes.append(("interaction", interaction_payload))
        ctx.core_lane_results.append({"name": "interaction", "status": "success"})
        return _created_id
    else:
        ctx.errors.append(("interaction", interaction_payload, err))
        ctx.core_lane_results.append({"name": "interaction", "status": "failed", "error": err})
        return None


def route_interaction_participants(ctx: RoutingContext, interaction_id: str):
    """Lane 1A: Register all resolved speakers as interaction participants."""
    _route_interaction_participants(
        interaction_id, ctx.conversation_id,
        ctx.networking_app_contact_id, ctx.sel_conn,
    )


def route_status_advance(ctx: RoutingContext, interaction_payload: dict):
    """Lane 1C: Advance contact status based on sentiment/delta after interaction.

    Secondary (non-fatal). Only fires when interaction was successfully created.
    """
    try:
        _sentiment = interaction_payload.get("sentiment", "neutral")
        _rel_delta = interaction_payload.get("relationshipDelta", "stable")

        # GET current contact to read status
        _sa_ok, _sa_err, _sa_contact = _core._api_call(
            "GET",
            f"{NETWORKING_APP_URL}/api/contacts/{ctx.networking_app_contact_id}",
            None,
        )
        if _sa_ok and isinstance(_sa_contact, dict):
            _old_status = (_sa_contact.get("status") or "").lower()
            _new_status = None

            # Transition rules
            if _old_status in ("target", "outreach_sent"):
                _new_status = "active"
            elif _old_status in ("cold", "dormant"):
                if _sentiment in ("warm", "enthusiastic"):
                    _new_status = "warm"
                elif _rel_delta == "strengthened":
                    _new_status = "warm"
            elif _old_status == "warm":
                _new_status = "active"

            if _new_status and _new_status != _old_status:
                _patch_ok, _patch_err, _ = _core._api_call(
                    "PATCH",
                    f"{NETWORKING_APP_URL}/api/contacts/{ctx.networking_app_contact_id}",
                    {"status": _new_status},
                )
                if _patch_ok:
                    logger.info(
                        "[ROUTING] Contact status advance: %s → %s for contact %s",
                        _old_status, _new_status, ctx.networking_app_contact_id,
                    )
                    ctx.secondary_lane_results.append({
                        "name": "status_advance",
                        "status": "success",
                        "from": _old_status,
                        "to": _new_status,
                    })
                else:
                    logger.warning(
                        "[ROUTING] Contact status advance PATCH failed for %s: %s",
                        ctx.networking_app_contact_id, _patch_err,
                    )
                    ctx.secondary_lane_results.append({
                        "name": "status_advance",
                        "status": "failed",
                        "error": _patch_err,
                    })
            else:
                logger.debug(
                    "[ROUTING] Contact status advance: no transition for status=%s "
                    "sentiment=%s delta=%s (contact %s)",
                    _old_status, _sentiment, _rel_delta, ctx.networking_app_contact_id,
                )
                ctx.secondary_lane_results.append({
                    "name": "status_advance",
                    "status": "skipped_no_transition",
                })
        elif not _sa_ok:
            logger.warning(
                "[ROUTING] Contact status advance: GET contact failed for %s: %s",
                ctx.networking_app_contact_id, _sa_err,
            )
            ctx.secondary_lane_results.append({
                "name": "status_advance",
                "status": "failed",
                "error": _sa_err,
            })
    except Exception as _sa_exc:
        logger.warning(
            "[ROUTING] Contact status advance exception for %s: %s",
            ctx.networking_app_contact_id, _sa_exc,
        )
        ctx.secondary_lane_results.append({
            "name": "status_advance",
            "status": "failed",
            "error": str(_sa_exc),
        })
