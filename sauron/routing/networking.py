"""Route extraction results to the Networking App.

# Architecture note (Cat4 Step J): Direct-write pattern confirmed.
# Sauron extracts structured intelligence -> routes directly to Networking API endpoints.
# No intermediate queue, batch job, or Networking-side re-extraction.
# Each routing lane maps a synthesis field to an API POST/PATCH call.

Uses review-gated direct writes with all-or-nothing routing per conversation.
If any API call fails, the entire conversation is logged as a single
'conversation_bundle' failure and can be retried as a unit.

See Integration Spec v2, Sections 10-11.

Phase B: Contact ID bridge, routing_log, pending-entity holds.
Phase B.5: Sentiment + relationship_delta from Opus with keyword fallback.
Phase C: Inline commitments, null-only contact patching, all-or-nothing routing.
"""

import json as _json
import logging
import uuid
from datetime import datetime

import httpx
from sauron.routing.provisional import store_provisional_org

from sauron.config import NETWORKING_APP_URL
from sauron.routing.contact_bridge import resolve_networking_contact_id
from sauron.routing.routing_log import (
    log_pending_entity,
    log_routing_failure,
    log_routing_success,
)

from sauron.routing.lanes.core import (
    RoutingSummary, TIMEOUT, _api_call, _store_routing_summary,
)
from sauron.routing.lanes.entity_resolution import (
    _resolve_contact_id_for_entity, _resolve_with_synthesis_links,
    _find_provisional_entity_id, _hold_pending_route, _SKIP_SENTINEL,
)
from sauron.routing.lanes.signals import (
    _route_provenance, _route_profile_intelligence, _route_affiliations,
    _infer_sentiment, _infer_delta,
)
from sauron.routing.lanes.commitments import (
    _collect_inline_commitments, _map_commitment_kind,
    _route_standalone_commitments, _collect_scheduling_leads,
    _route_interaction_participants, _update_contact_field_null_only,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════

def route_to_networking_app(
    conversation_id: str,
    extraction: dict,
    networking_app_contact_id: str | None = None,
) -> bool:
    """Route all relevant extraction data to the Networking App.

    All-or-nothing: if any API call fails, the entire conversation is
    logged as a single 'conversation_bundle' failure with the full
    extraction payload stored for retry. Upsert on sourceSystem/sourceId
    makes re-sending safe.

    Returns True if all calls succeeded, False if any failed or held.
    """
    # Unpack v6 three-pass result
    if "synthesis" in extraction:
        synthesis = extraction["synthesis"]
        claims = extraction.get("claims", {})
    else:
        synthesis = extraction
        claims = {}

    # ── Solo capture normalization ──────────────────────────────
    # Solo captures produce a flat SoloExtractionResult with different
    # field names than synthesis. Only debrief/prep modes contain
    # contact-relevant data worth routing to Networking.
    # Other modes (note, tasks, journal, general) stay internal.
    if "solo_mode" in synthesis:
        solo_mode = synthesis.get("solo_mode", "general")
        if solo_mode not in ("debrief", "prep"):
            logger.info(
                f"Solo mode '{solo_mode}' — skipping Networking routing "
                f"(not contact-relevant)"
            )
            return True  # Not an error, just nothing to route

        # Normalize solo fields into synthesis-compatible shape so
        # existing lanes pick them up. No solo-specific lanes.
        #
        # contact_follow_ups → follow_ups (inlined on interaction)
        solo_fus = synthesis.get("contact_follow_ups", [])
        if solo_fus and "follow_ups" not in synthesis:
            synthesis["follow_ups"] = [
                {
                    "description": (
                        fu.get("description", "") if isinstance(fu, dict)
                        else str(fu)
                    ),
                    "priority": (
                        fu.get("priority", "medium") if isinstance(fu, dict)
                        else "medium"
                    ),
                    "due_date": (
                        fu.get("due_date") if isinstance(fu, dict) else None
                    ),
                }
                for fu in solo_fus
                if (fu.get("description") if isinstance(fu, dict) else fu)
            ]

        # Resolve primary contact from linked_contact_names.
        # Solo captures have no speaker-based contact bridge — the
        # primary contact must come from who Stephen is debriefing
        # or prepping about. Require exactly one resolved contact;
        # ambiguous (multiple) or unresolvable (zero) → skip routing.
        linked_names = synthesis.get("linked_contact_names", [])
        resolved_contacts = []
        for name in linked_names:
            cid = _resolve_contact_id_for_entity(name, None)
            if cid:
                resolved_contacts.append((name, cid))

        if len(resolved_contacts) == 1:
            # Single resolved contact — use as primary for interaction
            _solo_contact_name, _solo_contact_id = resolved_contacts[0]
            networking_app_contact_id = _solo_contact_id
            # Tag synthesis so _execute_routing applies solo-specific
            # gating (no automatic interaction, strict contact resolution)
            synthesis["_solo_routing"] = True
            synthesis["_solo_mode"] = solo_mode
            logger.info(
                f"Solo {solo_mode}: resolved primary contact "
                f"'{_solo_contact_name}' → {_solo_contact_id[:8]}"
            )
        elif len(resolved_contacts) == 0:
            logger.info(
                f"Solo {solo_mode}: no linked contacts resolved — "
                f"skipping Networking routing"
            )
            return True
        else:
            # Multiple contacts resolved — ambiguous primary.
            # Skip rather than misattribute.
            logger.info(
                f"Solo {solo_mode}: {len(resolved_contacts)} contacts "
                f"resolved (ambiguous primary) — skipping Networking routing"
            )
            return True

    # Resolve contact ID if not provided
    if networking_app_contact_id is None:
        from sauron.db.connection import get_connection
        conn = get_connection()
        try:
            bridge = resolve_networking_contact_id(conversation_id, conn)
        finally:
            conn.close()

        if bridge is None:
            networking_app_contact_id = None
        elif not bridge["resolved"]:
            logger.info(
                f"Holding route for conversation {conversation_id[:8]}: "
                f"entity {bridge['canonical_name']} has no networking_app_contact_id"
            )
            log_pending_entity(
                conversation_id=conversation_id,
                entity_id=bridge["entity_id"],
                payload=extraction,
            )
            return False
        else:
            networking_app_contact_id = bridge["networking_app_contact_id"]

    # ── Open DB connection for synthesis_entity_links queries (Phase 4) ──
    from sauron.db.connection import get_connection as _get_conn
    sel_conn = _get_conn()
    try:
        return _execute_routing(
            conversation_id, synthesis, claims,
            networking_app_contact_id, extraction, sel_conn,
        )
    finally:
        sel_conn.close()


def _execute_routing(
    conversation_id, synthesis, claims,
    networking_app_contact_id, extraction, sel_conn,
):
    """Inner routing function with DB connection for synthesis_entity_links."""
    routing_attempt_id = str(uuid.uuid4())
    core_lane_results = []
    secondary_lane_results = []

    # Category 2 fields live at extraction top-level, not under synthesis.
    # Merge them into synthesis so lane functions find them via synthesis.get().
    for _cat2_key in (
        "status_changes", "org_intelligence", "provenance_observations",
        "per_speaker_vocal_insights", "what_changed", "vocal_intelligence_summary",
        "affiliation_mentions",  # Wave 2
    ):
        in_synth = _cat2_key in synthesis
        in_top = _cat2_key in extraction
        if not in_synth and in_top:
            synthesis[_cat2_key] = extraction[_cat2_key]
            _val = extraction[_cat2_key]
            _cnt = len(_val) if isinstance(_val, (list, dict)) else 1
            logger.info(f"Cat2 merge: {_cat2_key} merged from top-level ({_cnt} items)")
        elif in_synth:
            _val = synthesis[_cat2_key]
            _cnt = len(_val) if isinstance(_val, (list, dict)) else 1
            logger.debug(f"Cat2 merge: {_cat2_key} already in synthesis ({_cnt} items)")
        else:
            logger.debug(f"Cat2 merge: {_cat2_key} absent from both synthesis and top-level")

    # Debug: log lane counts before routing
    for _lane_key in ("status_changes", "org_intelligence", "provenance_observations"):
        _lane_val = synthesis.get(_lane_key)
        if _lane_val:
            _cnt = len(_lane_val) if isinstance(_lane_val, (list, dict)) else 1
            logger.info(f"Lane {_lane_key}: {_cnt} items to route")
        else:
            logger.info(f"Lane {_lane_key}: 0 items (empty or absent)")

    errors = []   # [(object_class, payload, error_str)]
    secondary_errors = []  # non-fatal: interest, activity, signal, resource
    successes = []  # [(object_class, payload)]

    # 1. Interaction with inline commitments + follow-ups
    #    Follow-ups routed via followUpRequired/followUpDescription (not standalone endpoint)
    #
    # Solo gate: solo captures should NOT always create Interaction rows.
    #   - debrief: create interaction ONLY if summary is substantive
    #     (describes a real meeting/relationship event, not just "I was
    #     thinking about X")
    #   - prep: do NOT create interaction (prep is forward-looking planning,
    #     not a past event; downstream lanes like follow-ups and calendar
    #     events handle prep outputs better)
    _is_solo = synthesis.get("_solo_routing", False)
    _solo_mode = synthesis.get("_solo_mode", "")
    _skip_interaction = False

    if _is_solo:
        if _solo_mode == "prep":
            _skip_interaction = True
            logger.info("Solo prep: skipping interaction creation (not a past event)")
        elif _solo_mode == "debrief":
            # Only create interaction if summary has real substance
            _summary = synthesis.get("summary", "")
            if len(_summary) < 30:
                _skip_interaction = True
                logger.info(
                    f"Solo debrief: skipping interaction (summary too thin: "
                    f"{len(_summary)} chars)"
                )

    if not _skip_interaction:
        commitments_inline = _collect_inline_commitments(synthesis)
        follow_ups = synthesis.get("follow_ups", [])
        interaction_payload = {
            "source": "sauron",
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "type": "conversation",
            "date": datetime.utcnow().isoformat() + "Z",
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
        if networking_app_contact_id:
            interaction_payload["contactId"] = networking_app_contact_id

        ok, err, _resp = _api_call("POST", f"{NETWORKING_APP_URL}/api/interactions", interaction_payload)
        _created_interaction_id = None
        if ok:
            # Capture interaction ID for participant routing
            if isinstance(_resp, dict):
                _created_interaction_id = _resp.get("id")
            successes.append(("interaction", interaction_payload))
            core_lane_results.append({"name": "interaction", "status": "success"})
        else:
            errors.append(("interaction", interaction_payload, err))
            core_lane_results.append({"name": "interaction", "status": "failed", "error": err})
    else:
        _created_interaction_id = None
        core_lane_results.append({"name": "interaction", "status": "skipped_solo"})

    # 1A. Interaction participants — multi-person tracking
    #     After interaction creation, register all resolved speakers as
    #     participants. Uses speaker-contact bridge from diarization.
    #     Only fires when interaction was actually created.
    if _created_interaction_id:
        _route_interaction_participants(
            _created_interaction_id, conversation_id,
            networking_app_contact_id, sel_conn,
        )

    # 1B. Standalone commitment records (secondary — non-fatal)
    commit_ok, commit_errs = _route_standalone_commitments(
        conversation_id, synthesis, networking_app_contact_id, sel_conn
    )
    successes.extend(commit_ok)
    secondary_errors.extend(commit_errs)
    if commit_errs:
        for _, _, e in commit_errs:
            secondary_lane_results.append({"name": "commitment", "status": "failed", "reason": e})
    elif commit_ok:
        secondary_lane_results.append({"name": "commitment", "status": "success"})
    else:
        secondary_lane_results.append({"name": "commitment", "status": "skipped_no_data"})

    # 2. Scheduling leads (social-firmness commitments + dedicated list)
    for lead_payload in _collect_scheduling_leads(conversation_id, synthesis, networking_app_contact_id, sel_conn):
        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/scheduling-leads", lead_payload
        )
        if ok:
            successes.append(("scheduling_lead", lead_payload))
        else:
            errors.append(("scheduling_lead", lead_payload, err))

    # Summarize scheduling_leads lane
    sched_errs = [e for c, _, e in errors if c == "scheduling_lead"]
    if sched_errs:
        core_lane_results.append({"name": "scheduling_leads", "status": "failed", "error": sched_errs[0]})
    else:
        core_lane_results.append({"name": "scheduling_leads", "status": "success"})

    # 3. Standing offers (Phase 4: prefer synthesis_entity_links)
    for idx, offer in enumerate(synthesis.get("standing_offers", [])):
        offer_cid = _resolve_with_synthesis_links(
            sel_conn, conversation_id, "standing_offer", idx, "contact_name",
            offer.get("contact_name", ""), networking_app_contact_id,
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
            "sourceId": conversation_id,
            "sourceClaimId": offer.get("source_claim_id"),
        }
        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/standing-offers", offer_payload
        )
        if ok:
            successes.append(("standing_offer", offer_payload))
        else:
            errors.append(("standing_offer", offer_payload, err))

    # Summarize standing_offers lane
    offer_errs = [e for c, _, e in errors if c == "standing_offer"]
    if offer_errs:
        core_lane_results.append({"name": "standing_offers", "status": "failed", "error": offer_errs[0]})
    else:
        core_lane_results.append({"name": "standing_offers", "status": "success"})

    # 4. Follow-ups — routed inline with Interaction (followUpRequired/followUpDescription)
    #    No standalone POST /api/follow-ups needed.

    # 5. Contact field updates — null-only patching (Phase C)
    for mw in claims.get("memory_writes", []):
        if mw.get("entity_type") != "person":
            continue
        if mw.get("field") in ("interest", "activity", "lifeEvent"):
            continue
        field_ok, field_err = _update_contact_field_null_only(
            mw, networking_app_contact_id
        )
        if field_ok is not None:  # None = skipped (already has value)
            if field_ok:
                successes.append(("contact_update", mw))
            else:
                errors.append(("contact_update", mw, field_err))

    # 6. Life events
    for mw in claims.get("memory_writes", []):
        if mw.get("field") != "lifeEvent" or not mw.get("entity_name"):
            continue
        contact_id = _resolve_contact_id_for_entity(
            mw.get("entity_name", ""), networking_app_contact_id
        )
        if not contact_id:
            continue
        le_payload = {
            "description": mw.get("value", ""),
            "person": mw.get("entity_name", "unknown"),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": mw.get("claim_id"),
        }
        ok, err, _resp = _api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/contacts/{contact_id}/life-events",
            le_payload,
        )
        if ok:
            successes.append(("life_event", le_payload))
        else:
            errors.append(("life_event", le_payload, err))

    # 7. Personal interests
    for mw in claims.get("memory_writes", []):
        if mw.get("field") != "interest":
            continue
        contact_id = _resolve_contact_id_for_entity(
            mw.get("entity_name", ""), networking_app_contact_id
        )
        if not contact_id:
            continue
        int_payload = {
            "contactId": contact_id,
            "interest": mw.get("value", ""),
            "source": "sauron",
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": mw.get("claim_id"),
        }
        ok, err, _resp = _api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/personal/interests",
            int_payload,
        )
        if ok:
            successes.append(("interest", int_payload))
        else:
            secondary_errors.append(("interest", int_payload, err))

    # 8. Personal activities
    for mw in claims.get("memory_writes", []):
        if mw.get("field") != "activity":
            continue
        contact_id = _resolve_contact_id_for_entity(
            mw.get("entity_name", ""), networking_app_contact_id
        )
        if not contact_id:
            continue
        act_payload = {
            "contactId": contact_id,
            "activity": mw.get("value", ""),
            "source": "sauron",
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": mw.get("claim_id"),
        }
        ok, err, _resp = _api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/personal/activities",
            act_payload,
        )
        if ok:
            successes.append(("activity", act_payload))
        else:
            secondary_errors.append(("activity", act_payload, err))

    # 9. Graph edges → ContactRelationship (Phase 4: prefer synthesis_entity_links)
    for idx, edge in enumerate(synthesis.get("graph_edges", [])):
        from_name = edge.get("from_entity", "")
        to_name = edge.get("to_entity", "")
        if not from_name or not to_name:
            continue
        # Phase 4: Resolve via synthesis_entity_links first, fallback to name-string
        from_cid = _resolve_with_synthesis_links(
            sel_conn, conversation_id, "graph_edge", idx, "from_entity",
            from_name, None,
        )
        to_cid = _resolve_with_synthesis_links(
            sel_conn, conversation_id, "graph_edge", idx, "to_entity",
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
            # Check if entities are provisional (unresolved) — hold for replay
            blocked_entity = None
            if not from_cid:
                blocked_entity = _find_provisional_entity_id(sel_conn, from_name)
            elif not to_cid:
                blocked_entity = _find_provisional_entity_id(sel_conn, to_name)

            if blocked_entity:
                _hold_pending_route(
                    sel_conn, conversation_id, "graph_edge",
                    {
                        "from_name": from_name,
                        "to_name": to_name,
                        "from_cid": from_cid,
                        "to_cid": to_cid,
                        "edge_type": edge.get("edge_type", "knows"),
                        "strength": edge.get("strength", 0.5),
                        "sourceSystem": "sauron",
                        "sourceId": conversation_id,
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
        pair = sorted([from_name, to_name])
        edge_payload = {
            "contactAId": from_cid,
            "contactBId": to_cid,
            "relationshipType": edge.get("edge_type", "knows"),
            "strength": int(edge.get("strength", 0.5) * 5) + 1,  # 0-1 float → 1-6 int
            "source": "sauron",
            "observationSource": f"Conversation {conversation_id[:8]}",
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": f"{pair[0]}:{pair[1]}:{edge.get('edge_type', 'knows')}",
        }
        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/contact-relationships", edge_payload
        )
        if ok:
            successes.append(("contact_relationship", edge_payload))
        else:
            errors.append(("contact_relationship", edge_payload, err))

    # Summarize graph_edges lane
    edge_errs = [e for c, _, e in errors if c == "contact_relationship"]
    if edge_errs:
        core_lane_results.append({"name": "graph_edges", "status": "failed", "error": edge_errs[0]})
    else:
        core_lane_results.append({"name": "graph_edges", "status": "success"})

    # 10. Intelligence signals from policy positions (Phase D)
    for pp in synthesis.get("policy_positions", []):
        person_name = pp.get("person", "")
        pp_contact_id = _resolve_contact_id_for_entity(
            person_name, networking_app_contact_id
        )
        if not pp_contact_id:
            continue
        sig_payload = {
            "contactId": pp_contact_id,
            "signalType": "policy_position",
            "title": f"{person_name}: {pp.get('topic', 'unknown topic')}",
            "description": pp.get("position", ""),
            "sourceName": "sauron",
            "relevanceScore": pp.get("strength", 0.5) * 10,  # 0-1 → 0-10
            "outreachHook": pp.get("notes") or None,
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": pp.get("claim_id"),
        }
        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/signals", sig_payload
        )
        if ok:
            successes.append(("intelligence_signal", sig_payload))
        else:
            secondary_errors.append(("intelligence_signal", sig_payload, err))

    # Summarize policy_positions lane
    pp_errs = [e for c, _, e in secondary_errors if c == "intelligence_signal"]
    if pp_errs:
        core_lane_results.append({"name": "policy_positions", "status": "failed", "error": pp_errs[0]})
    else:
        core_lane_results.append({"name": "policy_positions", "status": "success"})

    # 11. Referenced resources (Phase D)
    # Extraction layer doesn't yet produce a dedicated referenced_resources list.
    # Route them when available; future extraction prompt update will populate this.
    for res in synthesis.get("referenced_resources", []):
        res_contact_id = _resolve_contact_id_for_entity(
            res.get("contact_name", ""), networking_app_contact_id
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
            "sourceId": conversation_id,
            "sourceClaimId": res.get("source_claim_id"),
        }
        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/referenced-resources", res_payload
        )
        if ok:
            successes.append(("referenced_resource", res_payload))
        else:
            secondary_errors.append(("referenced_resource", res_payload, err))


    # Summarize interests lane
    int_errs = [e for c, _, e in secondary_errors if c == "interest"]
    if int_errs:
        secondary_lane_results.append({"name": "interests", "status": "failed", "reason": int_errs[0]})
    elif any(c == "interest" for c, _ in successes):
        secondary_lane_results.append({"name": "interests", "status": "success"})
    else:
        secondary_lane_results.append({"name": "interests", "status": "skipped_no_data"})

    # Summarize activities lane
    act_errs = [e for c, _, e in secondary_errors if c == "activity"]
    if act_errs:
        secondary_lane_results.append({"name": "activities", "status": "failed", "reason": act_errs[0]})
    elif any(c == "activity" for c, _ in successes):
        secondary_lane_results.append({"name": "activities", "status": "success"})
    else:
        secondary_lane_results.append({"name": "activities", "status": "skipped_no_data"})

    # Summarize referenced_resources lane
    res_errs = [e for c, _, e in secondary_errors if c == "referenced_resource"]
    if res_errs:
        secondary_lane_results.append({"name": "referenced_resources", "status": "failed", "reason": res_errs[0]})
    elif any(c == "referenced_resource" for c, _ in successes):
        secondary_lane_results.append({"name": "referenced_resources", "status": "success"})
    else:
        secondary_lane_results.append({"name": "referenced_resources", "status": "skipped_no_data"})

    # 10b. Status changes (secondary — non-fatal)
    _sc_list = synthesis.get("status_changes", [])
    logger.info(f"Lane 10b status_changes: {len(_sc_list)} items found in synthesis")
    for idx, sc in enumerate(_sc_list):
        contact_name = sc.get("contact_name", "")
        if not contact_name:
            continue

        if sel_conn is not None:
            sc_contact_id = _resolve_with_synthesis_links(
                sel_conn, conversation_id, "status_change", idx,
                "contact_name", contact_name, networking_app_contact_id,
            )
            if sc_contact_id == _SKIP_SENTINEL:
                logger.debug(f"Skipping status_change[{idx}]: person marked as skipped")
                continue
        else:
            sc_contact_id = _resolve_contact_id_for_entity(
                contact_name, networking_app_contact_id
            )

        if not sc_contact_id:
            logger.debug(f"Skipping status_change[{idx}]: could not resolve '{contact_name}'")
            continue

        # Build description with from/to state context when available (Cat4 Step C)
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
            "sourceId": conversation_id,
            "sourceClaimId": sc.get("source_claim_id"),
        }
        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/signals", sc_payload
        )
        if ok:
            successes.append(("status_change_signal", sc_payload))
        else:
            secondary_errors.append(("status_change_signal", sc_payload, err))

    # 10c. Org intelligence (secondary — non-fatal)
    # Routes to /api/organization-signals (org-level, no contactId required)
    _oi_list = synthesis.get("org_intelligence", [])
    logger.info(f"Lane 10c org_intelligence: {len(_oi_list)} items found in synthesis")
    for idx, oi in enumerate(_oi_list):
        org_name = oi.get("organization", "")
        if not org_name:
            continue

        # Build description: for org_relationship, preserve structured fields
        # in the description AND pass them as separate payload fields so
        # Networking can use them downstream if/when org relationships
        # get promoted to a first-class model.
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
            # Wave 2 expanded fields (Step 8D)
            "industry": oi.get("industry"),  # for industry_mention: triggers side-effect
            "relatedOrg": oi.get("related_org"),  # for org_relationship: structured field
            "relationshipType": oi.get("relationship_type"),  # for org_relationship
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": oi.get("source_claim_id"),
        }
        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/organization-signals", oi_payload
        )
        if ok:
            successes.append(("org_intel_signal", oi_payload))
        else:
            # Capture provisional org suggestion on 422 (org not resolved)
            if _resp and _resp.get("resolutionSource") == "provisional_suggestion":
                store_provisional_org(
                    raw_name=org_name,
                    normalized_name=org_name.lower().strip(),
                    conversation_id=conversation_id,
                    source_context=f"org_intelligence: {oi.get('intel_type', '')} - {oi.get('details', '')[:200]}",
                    resolution_source_context="provisional_suggestion",
                    suggested_by="org_intelligence",
                )
            elif err and "422" in err and "not resolved" in err.lower():
                store_provisional_org(
                    raw_name=org_name,
                    normalized_name=org_name.lower().strip(),
                    conversation_id=conversation_id,
                    source_context=f"org_intelligence: {oi.get('intel_type', '')} - {oi.get('details', '')[:200]}",
                    resolution_source_context=err[:200],
                    suggested_by="org_intelligence",
                )
            secondary_errors.append(("org_intel_signal", oi_payload, err))

    # 12. New contacts — REMOVED (Category 2, Step C)
    #     New contacts mentioned in conversations now flow through the
    #     Sauron provisional contact → People Review → confirm flow.
    #     No auto-creation of Networking contacts.

    # 13. Provenance observations (secondary — non-fatal)
    prov_ok, prov_errs = _route_provenance(
        conversation_id, synthesis, networking_app_contact_id, sel_conn
    )
    successes.extend(prov_ok)
    secondary_errors.extend(prov_errs)

    # 14. Per-contact profile intelligence (secondary — non-fatal)
    prof_ok, prof_errs = _route_profile_intelligence(
        conversation_id, synthesis, networking_app_contact_id, sel_conn
    )
    successes.extend(prof_ok)
    secondary_errors.extend(prof_errs)

    # 15. Affiliation mentions (secondary -- non-fatal, Wave 2)
    aff_ok, aff_errs = _route_affiliations(
        conversation_id, synthesis, networking_app_contact_id, sel_conn
    )
    successes.extend(aff_ok)
    secondary_errors.extend(aff_errs)

    # 16. Calendar events (secondary — non-fatal)
    #     Routes calendar_events from synthesis to Networking's Google Calendar
    #     integration. Attendee names are included in description/context rather
    #     than blocking event creation on unresolved contacts.
    for cal_event in synthesis.get("calendar_events", []):
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

        # Build description: include conversation context + attendee names (Cat4 Step F)
        desc_parts = [f"Source: Sauron conversation {conversation_id[:8]}"]
        if attendees:
            desc_parts.append(f"Mentioned attendees: {', '.join(attendees)}")
        if original_words:
            desc_parts.append(f'Original words: "{original_words}"')

        cal_payload = {
            "summary": title,
            "sourceSystem": "sauron",
            "sourceId": str(conversation_id),
            "sourceClaimId": cal_event.get("source_claim_id") or f"cal:{title[:60]}",
        }

        # Use explicit start_time/end_time if available (ISO datetime from extraction)
        if start_time:
            cal_payload["start"] = start_time
            cal_payload["end"] = end_time or start_time  # fallback end = start
            if is_placeholder:
                desc_parts.append(
                    "Note: Time is an inferred placeholder, not explicitly stated."
                )
        elif suggested_date:
            # Fallback: date only -> 9am-10am ET placeholder
            cal_payload["start"] = f"{suggested_date}T09:00:00-05:00"
            cal_payload["end"] = f"{suggested_date}T10:00:00-05:00"
            desc_parts.append(
                "Time placeholder inferred by Sauron; "
                "original extraction only provided a date."
            )
        else:
            # No date or time -> skip
            logger.debug(
                f"Skipping calendar_event '{title}': no date or time available"
            )
            continue

        cal_payload["description"] = "\n".join(desc_parts)

        if location:
            cal_payload["location"] = location

        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/calendar/events", cal_payload
        )
        if ok:
            successes.append(("calendar_event", cal_payload))
        else:
            secondary_errors.append(("calendar_event", cal_payload, err))

    # Summarize calendar_events lane
    cal_errs = [e for c, _, e in secondary_errors if c == "calendar_event"]
    if cal_errs:
        secondary_lane_results.append({"name": "calendar_events", "status": "failed", "reason": cal_errs[0]})
    elif any(c == "calendar_event" for c, _ in successes):
        secondary_lane_results.append({"name": "calendar_events", "status": "success"})
    else:
        secondary_lane_results.append({"name": "calendar_events", "status": "skipped_no_data"})

    # 17. Asks (secondary — non-fatal)
    #     Routes asks from synthesis to /api/commitments with kind="soft_ask".
    #     Asks are a form of commitment — someone is asking someone to do something.
    #     Using the commitment infrastructure gives us provenance, dedup, and tracking.
    _asks_list = synthesis.get("asks", [])
    logger.info(f"Lane 17 asks: {len(_asks_list)} items found in synthesis")
    for idx, ask in enumerate(_asks_list):
        contact_name = ask.get("contact_name", "") or ask.get("asked_of", "")
        if not contact_name:
            ask_cid = networking_app_contact_id
        elif sel_conn is not None:
            ask_cid = _resolve_with_synthesis_links(
                sel_conn, conversation_id, "ask", idx,
                "contact_name", contact_name, networking_app_contact_id,
            )
            if ask_cid == _SKIP_SENTINEL:
                logger.debug(f"Skipping ask[{idx}]: person marked as skipped")
                continue
        else:
            ask_cid = _resolve_contact_id_for_entity(
                contact_name, networking_app_contact_id
            )

        if not ask_cid:
            logger.debug(f"Skipping ask[{idx}]: could not resolve '{contact_name}'")
            continue

        # Map ask direction to commitment direction
        asked_by = ask.get("asked_by", "")
        # If I asked -> they owe me; if they asked -> I owe them
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
            "sourceId": conversation_id,
            "sourceClaimId": ask.get("source_claim_id"),
        }

        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/commitments", ask_payload
        )
        if ok:
            successes.append(("ask_commitment", ask_payload))
        else:
            secondary_errors.append(("ask_commitment", ask_payload, err))

    # Summarize asks lane
    ask_errs = [e for c, _, e in secondary_errors if c == "ask_commitment"]
    if ask_errs:
        secondary_lane_results.append({"name": "asks", "status": "failed", "reason": ask_errs[0]})
    elif any(c == "ask_commitment" for c, _ in successes):
        secondary_lane_results.append({"name": "asks", "status": "success"})
    else:
        secondary_lane_results.append({"name": "asks", "status": "skipped_no_data"})

    # 18. Life events from synthesis (secondary — non-fatal)
    #     Synthesis-level life_events complement Lane 6 (claims memory_writes).
    #     Routes to existing /api/contacts/{id}/life-events endpoint.
    _le_list = synthesis.get("life_events", [])
    logger.info(f"Lane 18 life_events: {len(_le_list)} items found in synthesis")
    for idx, le in enumerate(_le_list):
        contact_name = le.get("contact_name", "")
        if not contact_name:
            le_cid = networking_app_contact_id
        elif sel_conn is not None:
            le_cid = _resolve_with_synthesis_links(
                sel_conn, conversation_id, "life_event", idx,
                "contact_name", contact_name, networking_app_contact_id,
            )
            if le_cid == _SKIP_SENTINEL:
                logger.debug(f"Skipping life_event[{idx}]: person marked as skipped")
                continue
        else:
            le_cid = _resolve_contact_id_for_entity(
                contact_name, networking_app_contact_id
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
            "sourceId": conversation_id,
            "sourceClaimId": le.get("source_claim_id"),
        }

        ok, err, _resp = _api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/contacts/{le_cid}/life-events",
            le_payload,
        )
        if ok:
            successes.append(("synthesis_life_event", le_payload))
        else:
            secondary_errors.append(("synthesis_life_event", le_payload, err))

    # Summarize synthesis life_events lane
    sle_errs = [e for c, _, e in secondary_errors if c == "synthesis_life_event"]
    if sle_errs:
        secondary_lane_results.append({"name": "synthesis_life_events", "status": "failed", "reason": sle_errs[0]})
    elif any(c == "synthesis_life_event" for c, _ in successes):
        secondary_lane_results.append({"name": "synthesis_life_events", "status": "success"})
    else:
        secondary_lane_results.append({"name": "synthesis_life_events", "status": "skipped_no_data"})

        # Summarize status_changes lane
    sc_errs = [e for c, _, e in secondary_errors if c == "status_change_signal"]
    if sc_errs:
        secondary_lane_results.append({"name": "status_changes", "status": "failed", "reason": sc_errs[0]})
    elif any(c == "status_change_signal" for c, _ in successes):
        secondary_lane_results.append({"name": "status_changes", "status": "success"})
    else:
        secondary_lane_results.append({"name": "status_changes", "status": "skipped_no_data"})

    # Summarize org_intelligence lane
    oi_errs = [e for c, _, e in secondary_errors if c == "org_intel_signal"]
    if oi_errs:
        secondary_lane_results.append({"name": "org_intelligence", "status": "failed", "reason": oi_errs[0]})
    elif any(c == "org_intel_signal" for c, _ in successes):
        secondary_lane_results.append({"name": "org_intelligence", "status": "success"})
    else:
        secondary_lane_results.append({"name": "org_intelligence", "status": "skipped_no_data"})

    # Summarize provenance lane
    prov_errs_list = [e for c, _, e in secondary_errors if c == "provenance"]
    if prov_errs_list:
        secondary_lane_results.append({"name": "provenance", "status": "failed", "reason": prov_errs_list[0]})
    elif any(c == "provenance" for c, _ in successes):
        secondary_lane_results.append({"name": "provenance", "status": "success"})
    else:
        secondary_lane_results.append({"name": "provenance", "status": "skipped_no_data"})

    # Summarize profile_intelligence lane
    prof_errs_list = [e for c, _, e in secondary_errors if c == "profile_intelligence"]
    if prof_errs_list:
        secondary_lane_results.append({"name": "profile_intelligence", "status": "failed", "reason": prof_errs_list[0]})
    elif any(c == "profile_intelligence" for c, _ in successes):
        secondary_lane_results.append({"name": "profile_intelligence", "status": "success"})
    else:
        secondary_lane_results.append({"name": "profile_intelligence", "status": "skipped_no_data"})

    # Summarize affiliations lane (Wave 2)
    aff_errs_list = [e for c, _, e in secondary_errors if c == "affiliation"]
    if aff_errs_list:
        secondary_lane_results.append({"name": "affiliations", "status": "failed", "reason": aff_errs_list[0]})
    elif any(c == "affiliation" for c, _ in successes):
        secondary_lane_results.append({"name": "affiliations", "status": "success"})
    else:
        secondary_lane_results.append({"name": "affiliations", "status": "skipped_no_data"})

    # Collect pending entities
    pending_entities = []
    try:
        pending_rows = sel_conn.execute(
            "SELECT DISTINCT blocked_on_entity FROM pending_object_routes WHERE conversation_id = ? AND status = 'pending'",
            (conversation_id,)
        ).fetchall()
        pending_entities = [r[0] if isinstance(r, tuple) else r["blocked_on_entity"] for r in pending_rows]
    except Exception:
        pass

    # ── Verdict (secondary failures are non-fatal) ─────────────
    if secondary_errors:
        sec_summary = "; ".join(
            f"{obj}: {err}" for obj, _, err in secondary_errors
        )
        logger.warning(
            f"Routing had {len(secondary_errors)} non-fatal secondary error(s) "
            f"for conversation {conversation_id[:8]}: {sec_summary}"
        )
    if errors:
        error_summary = "; ".join(
            f"{obj}: {err}" for obj, _, err in errors
        )
        logger.warning(
            f"Routing FAILED for conversation {conversation_id[:8]} — "
            f"{len(errors)} error(s): {error_summary}"
        )
        log_routing_failure(
            conversation_id=conversation_id,
            object_class="conversation_bundle",
            payload=extraction,
            error=error_summary[:500],
        )
        summary = RoutingSummary(
            conversation_id=conversation_id,
            routing_attempt_id=routing_attempt_id,
            trigger_type="initial",
            final_state="failed",
            core_lanes=core_lane_results,
            secondary_lanes=secondary_lane_results,
            pending_entities=pending_entities,
            warning_count=len([s for s in secondary_lane_results if s.get("status") in {"skipped_blocked", "skipped_unresolved", "skipped_low_confidence"}]),
            error_count=len([s for s in secondary_lane_results if s.get("status") == "failed"]) + len(errors),
        )
        _store_routing_summary(summary, sel_conn)
        return False

    # All succeeded — log individual successes for audit trail
    for obj_class, payload in successes:
        log_routing_success(conversation_id, obj_class, payload)
    logger.info(
        f"Routed conversation {conversation_id[:8]} — "
        f"{len(successes)} object(s) sent successfully"
    )

    # Determine final state
    # Degraded statuses: failed, skipped_blocked, skipped_unresolved, skipped_low_confidence
    # NOT degraded: skipped_no_data (nothing to do = healthy)
    DEGRADED_STATUSES = {"failed", "skipped_blocked", "skipped_unresolved", "skipped_low_confidence"}
    has_degraded_secondary = any(s.get("status") in DEGRADED_STATUSES for s in secondary_lane_results)
    final_state = "success_with_partial_secondary_loss" if has_degraded_secondary else "success"

    summary = RoutingSummary(
        conversation_id=conversation_id,
        routing_attempt_id=routing_attempt_id,
        trigger_type="initial",
        final_state=final_state,
        core_lanes=core_lane_results,
        secondary_lanes=secondary_lane_results,
        pending_entities=pending_entities,
        warning_count=len([s for s in secondary_lane_results if s.get("status") in DEGRADED_STATUSES and s.get("status") != "failed"]),
        error_count=len([s for s in secondary_lane_results if s.get("status") == "failed"]),
    )
    _store_routing_summary(summary, sel_conn)
    return True
