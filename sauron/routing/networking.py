"""Route extraction results to the Networking App.

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

from sauron.config import NETWORKING_APP_URL
from sauron.routing.contact_bridge import resolve_networking_contact_id
from sauron.routing.routing_log import (
    log_pending_entity,
    log_routing_failure,
    log_routing_success,
)

from dataclasses import dataclass, field


@dataclass
class RoutingSummary:
    conversation_id: str
    routing_attempt_id: str  # UUID
    trigger_type: str  # initial, reroute, replay, solo
    final_state: str  # success, partial_secondary_loss, failed
    core_lanes: list = field(default_factory=list)  # [{name, status, error?}]
    secondary_lanes: list = field(default_factory=list)  # [{name, status, reason?}]
    pending_entities: list = field(default_factory=list)  # blocked entity names
    warning_count: int = 0
    error_count: int = 0

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=5.0)


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

    ok, err = _api_call("POST", f"{NETWORKING_APP_URL}/api/interactions", interaction_payload)
    if ok:
        successes.append(("interaction", interaction_payload))
        core_lane_results.append({"name": "interaction", "status": "success"})
    else:
        errors.append(("interaction", interaction_payload, err))
        core_lane_results.append({"name": "interaction", "status": "failed", "error": err})

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

    # 2. Scheduling leads (social-firmness commitments + dedicated list)
    for lead_payload in _collect_scheduling_leads(conversation_id, synthesis, networking_app_contact_id, sel_conn):
        ok, err = _api_call(
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
        offer_payload = {
            "contactId": offer_cid,
            "contactName": offer.get("contact_name", ""),
            "description": offer.get("description", ""),
            "offeredBy": offer.get("offered_by", "them"),
            "originalWords": offer.get("original_words", ""),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
        }
        ok, err = _api_call(
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
        }
        ok, err = _api_call(
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
        ok, err = _api_call(
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
        ok, err = _api_call(
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
        edge_payload = {
            "contactAId": from_cid,
            "contactBId": to_cid,
            "relationshipType": edge.get("edge_type", "knows"),
            "strength": int(edge.get("strength", 0.5) * 5) + 1,  # 0-1 float → 1-6 int
            "source": "sauron",
            "observationSource": f"Conversation {conversation_id[:8]}",
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
        }
        ok, err = _api_call(
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
        ok, err = _api_call(
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
        res_payload = {
            "contactId": res_contact_id,
            "description": res.get("description", ""),
            "resourceType": res.get("resource_type", "other"),
            "url": res.get("url"),
            "action": res.get("action", "reference_only"),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": res.get("claim_id"),
        }
        ok, err = _api_call(
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

    # Summarize activities lane
    act_errs = [e for c, _, e in secondary_errors if c == "activity"]
    if act_errs:
        secondary_lane_results.append({"name": "activities", "status": "failed", "reason": act_errs[0]})
    elif any(c == "activity" for c, _ in successes):
        secondary_lane_results.append({"name": "activities", "status": "success"})

    # Summarize referenced_resources lane
    res_errs = [e for c, _, e in secondary_errors if c == "referenced_resource"]
    if res_errs:
        secondary_lane_results.append({"name": "referenced_resources", "status": "failed", "reason": res_errs[0]})
    elif any(c == "referenced_resource" for c, _ in successes):
        secondary_lane_results.append({"name": "referenced_resources", "status": "success"})

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

        sc_payload = {
            "contactId": sc_contact_id,
            "signalType": "status_change",
            "title": f"{contact_name}: {sc.get('change_type', 'update')}",
            "description": sc.get("details", ""),
            "sourceName": "sauron",
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": sc.get("source_claim_id"),
        }
        ok, err = _api_call(
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

        oi_payload = {
            "organizationName": org_name,
            "signalType": oi.get("intel_type", "intelligence"),
            "title": f"{org_name}: {oi.get('intel_type', 'intelligence')}",
            "description": oi.get("details", ""),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": oi.get("source_claim_id"),
        }
        ok, err = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/organization-signals", oi_payload
        )
        if ok:
            successes.append(("org_intel_signal", oi_payload))
        else:
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

    # Summarize status_changes lane
    sc_errs = [e for c, _, e in secondary_errors if c == "status_change_signal"]
    if sc_errs:
        secondary_lane_results.append({"name": "status_changes", "status": "failed", "reason": sc_errs[0]})
    elif any(c == "status_change_signal" for c, _ in successes):
        secondary_lane_results.append({"name": "status_changes", "status": "success"})

    # Summarize org_intelligence lane
    oi_errs = [e for c, _, e in secondary_errors if c == "org_intel_signal"]
    if oi_errs:
        secondary_lane_results.append({"name": "org_intelligence", "status": "failed", "reason": oi_errs[0]})
    elif any(c == "org_intel_signal" for c, _ in successes):
        secondary_lane_results.append({"name": "org_intelligence", "status": "success"})

    # Summarize provenance lane
    prov_errs_list = [e for c, _, e in secondary_errors if c == "provenance"]
    if prov_errs_list:
        secondary_lane_results.append({"name": "provenance", "status": "failed", "reason": prov_errs_list[0]})
    elif any(c == "provenance" for c, _ in successes):
        secondary_lane_results.append({"name": "provenance", "status": "success"})

    # Summarize profile_intelligence lane
    prof_errs_list = [e for c, _, e in secondary_errors if c == "profile_intelligence"]
    if prof_errs_list:
        secondary_lane_results.append({"name": "profile_intelligence", "status": "failed", "reason": prof_errs_list[0]})
    elif any(c == "profile_intelligence" for c, _ in successes):
        secondary_lane_results.append({"name": "profile_intelligence", "status": "success"})

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
            warning_count=len([s for s in secondary_lane_results if s.get("status") == "skipped"]),
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
    has_secondary_failures = any(s.get("status") == "failed" for s in secondary_lane_results)
    final_state = "partial_secondary_loss" if has_secondary_failures else "success"

    summary = RoutingSummary(
        conversation_id=conversation_id,
        routing_attempt_id=routing_attempt_id,
        trigger_type="initial",
        final_state=final_state,
        core_lanes=core_lane_results,
        secondary_lanes=secondary_lane_results,
        pending_entities=pending_entities,
        warning_count=len([s for s in secondary_lane_results if s.get("status") == "skipped"]),
        error_count=len([s for s in secondary_lane_results if s.get("status") == "failed"]),
    )
    _store_routing_summary(summary, sel_conn)
    return True



def _store_routing_summary(summary: RoutingSummary, conn=None):
    """Persist routing summary to the routing_summaries table."""
    import json as _js
    from sauron.db.connection import get_connection
    db_conn = conn or get_connection()
    close_conn = conn is None
    try:
        db_conn.execute(
            """INSERT INTO routing_summaries
               (conversation_id, routing_attempt_id, trigger_type, final_state,
                core_lanes, secondary_lanes, pending_entities, warning_count, error_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (summary.conversation_id, summary.routing_attempt_id, summary.trigger_type,
             summary.final_state, _js.dumps(summary.core_lanes), _js.dumps(summary.secondary_lanes),
             _js.dumps(summary.pending_entities), summary.warning_count, summary.error_count)
        )
        db_conn.commit()
    finally:
        if close_conn:
            db_conn.close()


# ═══════════════════════════════════════════════════════════════
# Payload builders
# ═══════════════════════════════════════════════════════════════

def _collect_inline_commitments(synthesis: dict) -> list[dict]:
    """Build commitments array for inline inclusion in Interaction payload.

    All firmness levels are now included (social and tentative no longer
    filtered out). The Networking App POST /api/interactions creates
    Commitment rows with interactionId automatically from this array.
    """
    inline = []
    for source_list, direction in [
        (synthesis.get("my_commitments", []), "i_owe"),
        (synthesis.get("contact_commitments", []), "they_owe"),
    ]:
        for c in source_list:
            firmness = c.get("firmness", "intentional")
            # Map direction to Networking App prefix
            prefix = "[Mine]" if direction in ("i_owe", "owed_by_me") else "[Theirs]"
            # Map firmness to kind
            kind = _map_commitment_kind(firmness)
            inline.append({
                "description": f"{prefix} {c.get('description', '')}",
                "dueDate": c.get("resolved_date") or c.get("due_date") or c.get("dueDate"),
                "sourceClaimId": c.get("source_claim_id"),
                "direction": direction,
                "kind": kind,
                "firmness": firmness,
            })
    return inline


def _map_commitment_kind(firmness: str) -> str:
    """Map extraction firmness to Networking commitment kind."""
    if firmness in ("concrete", "intentional"):
        return "commitment"
    elif firmness == "social":
        return "scheduling"
    elif firmness == "tentative":
        return "soft_ask"
    return "commitment"



def _route_standalone_commitments(
    conversation_id: str,
    synthesis: dict,
    networking_app_contact_id: str | None,
    sel_conn=None,
) -> tuple[list[tuple], list[tuple]]:
    """Lane 1B: Route each commitment as a first-class Commitment record.

    POSTs to /api/commitments with direction, kind, firmness.
    This is SECONDARY — failure does not block core interaction routing.
    Inline commitments on the Interaction are kept for compatibility.
    """
    successes = []
    sec_errors = []

    for source_list, direction in [
        (synthesis.get("my_commitments", []), "i_owe"),
        (synthesis.get("contact_commitments", []), "they_owe"),
    ]:
        for idx, c in enumerate(source_list):
            # SKIP: Commitments without sourceClaimId must not be posted
            # standalone.  Lane 1 (inline interaction routing) already creates
            # these rows via the dual-write path in POST /api/interactions.
            # Lane 1B only adds value when it can address a specific commitment
            # deterministically via the full provenance triple
            # (sourceSystem, sourceId, sourceClaimId).  Without sourceClaimId,
            # the /api/commitments upsert cannot match the existing row and
            # would create a duplicate.  Do not invent a fallback dedup rule
            # here — rely on the inline path for claim-ID-less commitments.
            if not c.get("source_claim_id"):
                logger.debug(
                    f"Lane 1B: skipping standalone commitment [{idx}] "
                    f"(direction={direction}): no sourceClaimId — "
                    f"covered by inline dual-write"
                )
                continue
            firmness = c.get("firmness", "intentional")
            kind = _map_commitment_kind(firmness)

            # Resolve contact via synthesis_entity_links
            assignee = c.get("assignee", "")
            if sel_conn is not None and assignee:
                obj_type = "my_commitment" if direction == "i_owe" else "contact_commitment"
                cid = _resolve_with_synthesis_links(
                    sel_conn, conversation_id, obj_type, idx, "assignee",
                    assignee, networking_app_contact_id,
                )
                if cid == _SKIP_SENTINEL:
                    logger.debug(f"Skipping commitment[{idx}]: person marked as skipped")
                    continue
            else:
                cid = networking_app_contact_id

            payload = {
                "contactId": cid,
                "description": c.get("description", ""),
                "dueDate": c.get("resolved_date") or c.get("due_date"),
                "direction": direction,
                "kind": kind,
                "firmness": firmness,
                "sourceSystem": "sauron",
                "sourceId": conversation_id,
                "sourceClaimId": c.get("source_claim_id"),
            }

            ok, err = _api_call(
                "POST", f"{NETWORKING_APP_URL}/api/commitments", payload
            )
            if ok:
                successes.append(("commitment", payload))
            else:
                sec_errors.append(("commitment", payload, err))

    return successes, sec_errors

def _collect_scheduling_leads(
    conversation_id: str,
    synthesis: dict,
    networking_app_contact_id: str | None,
    sel_conn=None,
) -> list[dict]:
    """Collect all scheduling lead payloads.

    Sources: dedicated scheduling_leads list + social-firmness commitments.
    Each payload includes contactId resolved via synthesis_entity_links
    (Phase 4) with fallback to contact bridge.
    """
    leads = []

    for idx, lead in enumerate(synthesis.get("scheduling_leads", [])):
        if sel_conn is not None:
            lead_cid = _resolve_with_synthesis_links(
                sel_conn, conversation_id, "scheduling_lead", idx, "contact_name",
                lead.get("contact_name", ""), networking_app_contact_id,
            )
            if lead_cid == _SKIP_SENTINEL:
                logger.debug(f"Skipping scheduling_lead[{idx}]: person marked as skipped")
                continue
        else:
            lead_cid = _resolve_contact_id_for_entity(
                lead.get("contact_name", ""), networking_app_contact_id
            )
        leads.append({
            "contactId": lead_cid,
            "contactName": lead.get("contact_name", ""),
            "description": lead.get("description", ""),
            "originalWords": lead.get("original_words", ""),
            "timeframe": lead.get("timeframe"),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
        })

    for source_list in [
        synthesis.get("my_commitments", []),
        synthesis.get("contact_commitments", []),
    ]:
        for c in source_list:
            if c.get("firmness") == "social":
                social_cid = _resolve_contact_id_for_entity(
                    c.get("contact_name", ""), networking_app_contact_id
                )
                leads.append({
                    "contactId": social_cid,
                    "contactName": c.get("contact_name", ""),
                    "description": c.get("description", ""),
                    "originalWords": c.get("original_words", ""),
                    "timeframe": c.get("resolved_date"),
                    "sourceSystem": "sauron",
                    "sourceId": conversation_id,
                })

    return leads


# ═══════════════════════════════════════════════════════════════
# API call helper
# ═══════════════════════════════════════════════════════════════

def _api_call(
    method: str, url: str, payload: dict
) -> tuple[bool, str | None]:
    """Execute a single API call. Returns (success, error_or_None)."""
    try:
        if method == "POST":
            resp = httpx.post(url, json=payload, timeout=TIMEOUT)
        elif method == "PUT":
            resp = httpx.put(url, json=payload, timeout=TIMEOUT)
        elif method == "GET":
            resp = httpx.get(url, timeout=TIMEOUT)
        else:
            return False, f"Unsupported method: {method}"

        if resp.status_code < 300:
            return True, None
        else:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except httpx.ConnectError:
        return False, "ConnectError: Networking app not reachable"
    except Exception as e:
        return False, str(e)[:300]


# ═══════════════════════════════════════════════════════════════
# Contact resolution + null-only patching
# ═══════════════════════════════════════════════════════════════

def _route_provenance(
    conversation_id: str,
    synthesis: dict,
    networking_app_contact_id: str | None,
    sel_conn=None,
) -> tuple[list[tuple], list[tuple]]:
    """Lane 13: Route provenance observations to Networking App.

    Provenance describes how a person entered the network (referral, conference, etc.).
    POSTs to /api/contact-provenance. Secondary lane — non-fatal.
    """
    successes = []
    sec_errors = []

    for idx, prov in enumerate(synthesis.get("provenance_observations", [])):
        contact_name = prov.get("contact_name", "")
        if not contact_name:
            continue

        # Resolve the contact
        if sel_conn is not None:
            contact_cid = _resolve_with_synthesis_links(
                sel_conn, conversation_id, "provenance_observation", idx,
                "contact_name", contact_name, networking_app_contact_id,
            )
            if contact_cid == _SKIP_SENTINEL:
                logger.debug(f"Skipping provenance[{idx}]: person marked as skipped")
                continue
        else:
            contact_cid = _resolve_contact_id_for_entity(
                contact_name, networking_app_contact_id
            )

        if not contact_cid:
            logger.debug(f"Skipping provenance[{idx}]: could not resolve '{contact_name}'")
            continue

        # Resolve the introducer if present
        introduced_by = prov.get("introduced_by", "")
        source_contact_id = None
        if introduced_by:
            source_contact_id = _resolve_contact_id_for_entity(
                introduced_by, networking_app_contact_id
            )

        # Determine provenance type
        prov_type = prov.get("discovered_via") or "conversation"

        payload = {
            "contactId": contact_cid,
            "sourceContactId": source_contact_id,  # nullable — non-person provenance allowed
            "type": prov_type,
            "notes": prov.get("context", ""),
            "eventId": prov.get("event_id"),
            "sourceInteractionId": prov.get("source_interaction_id"),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": prov.get("source_claim_id"),
        }

        ok, err = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/contact-provenance", payload
        )
        if ok:
            successes.append(("provenance", payload))
        else:
            sec_errors.append(("provenance", payload, err))

    return successes, sec_errors

def _route_profile_intelligence(
    conversation_id: str,
    synthesis: dict,
    networking_app_contact_id: str | None,
    sel_conn=None,
) -> tuple[list[tuple], list[tuple]]:
    """Lane 14: Route per-contact profile intelligence to Networking App.

    Sources:
    - per_speaker_vocal_insights: emotional state, rapport, engagement, style
    - what_changed: key observation deltas
    - vocal_intelligence_summary: overall vocal analysis summary

    POSTs to /api/contact-profile-signals. Secondary lane — non-fatal.
    """
    successes = []
    sec_errors = []

    # A. Per-speaker vocal insights
    for speaker_name, insight in synthesis.get("per_speaker_vocal_insights", {}).items():
        if not speaker_name or speaker_name.lower() in ("unknown", "speaker_00", "speaker_01"):
            continue

        if sel_conn is not None:
            speaker_cid = _resolve_with_synthesis_links(
                sel_conn, conversation_id, "vocal_insight", 0,
                "speaker_name", speaker_name, networking_app_contact_id,
            )
            if speaker_cid == _SKIP_SENTINEL:
                logger.debug(f"Skipping vocal insight for '{speaker_name}': marked as skipped")
                continue
        else:
            speaker_cid = _resolve_contact_id_for_entity(
                speaker_name, networking_app_contact_id
            )

        if not speaker_cid:
            logger.debug(f"Skipping vocal insight for '{speaker_name}': could not resolve")
            continue

        # Route each non-null field as a separate profile signal
        insight_dict = insight if isinstance(insight, dict) else {}
        signal_fields = [
            ("emotional_state", insight_dict.get("emotional_state")),
            ("rapport_assessment", insight_dict.get("rapport_assessment")),
            ("engagement_trend", insight_dict.get("engagement_trend")),
            ("communication_style", insight_dict.get("communication_style_notes")),
        ]

        # Combine list fields into text
        passions = insight_dict.get("topics_of_passion", [])
        if passions:
            signal_fields.append(("topics_of_passion", ", ".join(passions)))
        discomforts = insight_dict.get("topics_of_discomfort", [])
        if discomforts:
            signal_fields.append(("topics_of_discomfort", ", ".join(discomforts)))

        for field_name, value in signal_fields:
            if not value:
                continue

            payload = {
                "contactId": speaker_cid,
                "signalType": f"vocal_{field_name}",
                "content": value,
                "conversationDate": synthesis.get("conversation_date"),
                "sourceSystem": "sauron",
                "sourceId": conversation_id,
            }
            ok, err = _api_call(
                "POST", f"{NETWORKING_APP_URL}/api/contact-profile-signals", payload
            )
            if ok:
                successes.append(("profile_signal", payload))
            else:
                sec_errors.append(("profile_signal", payload, err))

    # B. What changed observations
    for key, description in synthesis.get("what_changed", {}).items():
        if not description:
            continue

        # what_changed keys are often person names or topics
        # Try to resolve as a contact; if not resolvable, use primary contact
        if sel_conn is not None:
            wc_cid = _resolve_with_synthesis_links(
                sel_conn, conversation_id, "what_changed", 0,
                "key", key, networking_app_contact_id,
            )
            if wc_cid == _SKIP_SENTINEL:
                continue
        else:
            wc_cid = _resolve_contact_id_for_entity(key, networking_app_contact_id)

        if not wc_cid:
            wc_cid = networking_app_contact_id  # fallback to primary contact

        if not wc_cid:
            continue

        payload = {
            "contactId": wc_cid,
            "signalType": "what_changed",
            "content": f"{key}: {description}",
            "conversationDate": synthesis.get("conversation_date"),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
        }
        ok, err = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/contact-profile-signals", payload
        )
        if ok:
            successes.append(("what_changed_signal", payload))
        else:
            sec_errors.append(("what_changed_signal", payload, err))

    # C. Vocal intelligence summary (single signal for primary contact)
    vis = synthesis.get("vocal_intelligence_summary")
    if vis and networking_app_contact_id:
        payload = {
            "contactId": networking_app_contact_id,
            "signalType": "vocal_summary",
            "content": vis,
            "conversationDate": synthesis.get("conversation_date"),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
        }
        ok, err = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/contact-profile-signals", payload
        )
        if ok:
            successes.append(("vocal_summary", payload))
        else:
            sec_errors.append(("vocal_summary", payload, err))

    return successes, sec_errors

def _find_provisional_entity_id(conn, name: str) -> str | None:
    """Look up a provisional (unconfirmed) unified_contact by name."""
    if not conn or not name:
        return None
    name_lower = name.lower().strip()
    row = conn.execute(
        """SELECT id FROM unified_contacts
           WHERE (LOWER(canonical_name) = ? OR LOWER(aliases) LIKE ?)
             AND is_confirmed = 0""",
        (name_lower, f"%{name_lower}%"),
    ).fetchone()
    return row["id"] if row else None


def _hold_pending_route(conn, conversation_id: str, route_type: str,
                         payload: dict, blocked_on_entity: str):
    """Insert a pending object route for replay when entity is confirmed."""
    import json as _json
    route_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO pending_object_routes
           (id, conversation_id, route_type, payload, blocked_on_entity, status)
           VALUES (?, ?, ?, ?, ?, 'pending')""",
        (route_id, conversation_id, route_type, _json.dumps(payload), blocked_on_entity),
    )
    conn.commit()


def _resolve_contact_id_for_entity(
    entity_name: str, fallback_contact_id: str | None
) -> str | None:
    """Resolve a Networking App contact ID for an entity name.

    Uses local DB lookup (contact bridge), NOT HTTP name-string search.
    Falls back to the conversation's primary contact ID.
    """
    if not entity_name:
        return fallback_contact_id

    from sauron.db.connection import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT networking_app_contact_id FROM unified_contacts
               WHERE LOWER(canonical_name) = LOWER(?)
                  OR LOWER(aliases) LIKE LOWER(?)""",
            (entity_name.strip(), f"%{entity_name.strip()}%"),
        ).fetchone()
        if row and row["networking_app_contact_id"]:
            return row["networking_app_contact_id"]
        return fallback_contact_id
    finally:
        conn.close()


_SKIP_SENTINEL = "SKIP"


def _resolve_with_synthesis_links(
    conn,
    conversation_id: str,
    object_type: str,
    object_index: int,
    field_name: str,
    entity_name: str,
    fallback_contact_id: str | None,
) -> str | None:
    """Resolve a Networking App contact ID, preferring synthesis_entity_links.

    Phase 4: The synthesis linker (Phase 1) and review UI (Phase 3) resolve
    entities earlier in the pipeline and store results in synthesis_entity_links.
    This function checks those pre-resolved links first, falling back to
    name-string matching for backward compatibility.

    Returns:
        networking_app_contact_id (str) — resolved successfully
        _SKIP_SENTINEL — object should be skipped (user marked person as skipped)
        None — could not resolve
    """
    try:
        row = conn.execute("""
            SELECT sel.resolved_entity_id, sel.link_source,
                   uc.networking_app_contact_id
            FROM synthesis_entity_links sel
            LEFT JOIN unified_contacts uc ON uc.id = sel.resolved_entity_id
            WHERE sel.conversation_id = ?
              AND sel.object_type = ?
              AND sel.object_index = ?
              AND sel.field_name = ?
        """, (conversation_id, object_type, object_index, field_name)).fetchone()

        if row:
            if row["link_source"] == "skipped":
                return _SKIP_SENTINEL
            if row["resolved_entity_id"] and row["networking_app_contact_id"]:
                return row["networking_app_contact_id"]
            # Has synthesis link but entity has no networking_app_contact_id
            # (e.g., provisional or unsynced contact) — fall through to old resolution
    except Exception:
        logger.debug(f"synthesis_entity_links lookup failed for {object_type}[{object_index}].{field_name}")

    # Fallback: old name-string resolution (backward compat)
    return _resolve_contact_id_for_entity(entity_name, fallback_contact_id)


def _update_contact_field_null_only(
    memory_write: dict, fallback_contact_id: str | None
) -> tuple[bool | None, str | None]:
    """Update a contact field only if the current value is null.

    Phase C: Fetches the contact first and checks whether the target
    field already has a non-null/non-empty value. If it does, the
    update is skipped to avoid overwriting user-curated data.

    Preserves array fields (categories, tags) that the PUT handler
    would otherwise wipe via its || [] fallback.

    Returns:
        (True, None)  — updated successfully
        (False, err)  — API call failed
        (None, None)  — skipped (field has value, or no contact ID)
    """
    entity_name = memory_write.get("entity_name", "")
    field = memory_write.get("field", "")
    value = memory_write.get("value", "")

    if not entity_name or not field or not value:
        return None, None

    contact_id = _resolve_contact_id_for_entity(entity_name, fallback_contact_id)
    if not contact_id:
        return None, None

    # Map Sauron field names → Networking App field names
    field_map = {
        "employer": "organization",
        "company": "organization",
        "job_title": "title",
        "role": "title",
        "email_address": "email",
        "phone_number": "phone",
        "linkedin": "linkedinUrl",
        "twitter": "twitterHandle",
        "website": "personalWebsite",
    }
    net_field = field_map.get(field, field)

    # Only update fields that exist on the Networking App Contact model.
    # Opus extracts many custom fields (careerHistory, witnessStatus, etc.)
    # that have no corresponding column — sending them causes Prisma 500.
    VALID_CONTACT_FIELDS = {
        "name", "title", "organization", "email", "phone",
        "linkedinUrl", "twitterHandle", "personalWebsite",
        "tier", "status", "contactType", "notes",
        "introductionPathway", "connectionToHawleyOrbit", "whyTheyMatter",
        "targetCadenceDays",
    }
    if net_field not in VALID_CONTACT_FIELDS:
        logger.debug(
            f"Skipping {entity_name}.{field} → {net_field} — not a Contact model field"
        )
        return None, None

    # GET current contact
    try:
        resp = httpx.get(
            f"{NETWORKING_APP_URL}/api/contacts/{contact_id}",
            timeout=TIMEOUT,
        )
        if resp.status_code >= 300:
            return False, f"GET contact {contact_id[:8]} failed: HTTP {resp.status_code}"
        contact = resp.json()
    except httpx.ConnectError:
        return False, "ConnectError: Networking app not reachable"
    except Exception as e:
        return False, f"GET contact failed: {e}"

    # Null-only check: skip if field already has a value
    current = contact.get(net_field)
    if current is not None and str(current).strip() != "":
        logger.debug(
            f"Skipping {entity_name}.{net_field} — already has value"
        )
        return None, None

    # The Networking App only has PUT (no PATCH). Prisma's update()
    # sets any field not in the body to undefined → null, which would
    # wipe every other field on the contact. We must send the full
    # contact back with only our target field changed.
    #
    # Parse array fields from JSON strings so they survive the round-trip.
    cats = contact.get("categories")
    if isinstance(cats, str):
        try:
            cats = _json.loads(cats)
        except (ValueError, TypeError):
            cats = []
    tags = contact.get("tags")
    if isinstance(tags, str):
        try:
            tags = _json.loads(tags)
        except (ValueError, TypeError):
            tags = []

    # Build full body from fetched contact, overriding only the target field
    update_body = {
        "name": contact.get("name"),
        "title": contact.get("title"),
        "organization": contact.get("organization"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "linkedinUrl": contact.get("linkedinUrl"),
        "twitterHandle": contact.get("twitterHandle"),
        "personalWebsite": contact.get("personalWebsite"),
        "tier": contact.get("tier"),
        "categories": cats or [],
        "tags": tags or [],
        "targetCadenceDays": contact.get("targetCadenceDays"),
        "status": contact.get("status"),
        "contactType": contact.get("contactType"),
        "introductionPathway": contact.get("introductionPathway"),
        "connectionToHawleyOrbit": contact.get("connectionToHawleyOrbit"),
        "whyTheyMatter": contact.get("whyTheyMatter"),
        "notes": contact.get("notes"),
    }
    update_body[net_field] = value

    ok, err = _api_call(
        "PUT",
        f"{NETWORKING_APP_URL}/api/contacts/{contact_id}",
        update_body,
    )
    if ok:
        logger.info(f"Updated {entity_name}.{net_field} (was null)")
    return ok, err


# ═══════════════════════════════════════════════════════════════
# Sentiment + relationship delta (Phase B.5)
# ═══════════════════════════════════════════════════════════════

def _infer_sentiment(synthesis: dict) -> str | None:
    """Get sentiment — prefer explicit Opus field, fall back to keyword inference."""
    explicit = synthesis.get("sentiment")
    if explicit and explicit in (
        "warm", "neutral", "transactional", "tense", "enthusiastic"
    ):
        return explicit

    notes = synthesis.get("relationship_notes", "")
    if not notes:
        return None
    notes_lower = notes.lower()
    if any(w in notes_lower for w in ("warm", "positive", "strong", "building")):
        return "warm"
    if any(w in notes_lower for w in ("enthusiastic", "excited", "energetic")):
        return "enthusiastic"
    if any(w in notes_lower for w in ("tense", "cold", "strained", "cooling")):
        return "tense"
    if any(w in notes_lower for w in ("transactional", "business", "formal")):
        return "transactional"
    return "neutral"


def _infer_delta(synthesis: dict) -> str | None:
    """Get relationship delta — prefer explicit Opus field, fall back to keyword inference."""
    explicit = synthesis.get("relationship_delta")
    if explicit and explicit in (
        "strengthened", "maintained", "weakened", "new"
    ):
        return explicit

    notes = synthesis.get("relationship_notes", "")
    if not notes:
        return None
    notes_lower = notes.lower()
    if any(w in notes_lower for w in ("strengthen", "deepen", "warming", "closer")):
        return "strengthened"
    if any(w in notes_lower for w in ("strain", "tension", "cooling", "distance")):
        return "weakened"
    if any(w in notes_lower for w in ("first time", "new relationship", "just met", "initial")):
        return "new"
    return "maintained"
