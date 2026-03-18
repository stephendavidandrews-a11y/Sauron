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

import logging
import uuid


from sauron.config import NETWORKING_APP_URL
from sauron.routing.contact_bridge import resolve_networking_contact_id
from sauron.routing.routing_log import (
    log_pending_entity,
    log_routing_failure,
    log_routing_success,
)

from sauron.routing.lanes import core as _core
from sauron.routing.lanes.core import RoutingSummary, RoutingContext, _summarize_lane
from sauron.routing.lanes.relationships import route_graph_edges
from sauron.routing.lanes.personal import (
    route_life_events_from_claims, route_interests, route_activities,
    route_life_events_from_synthesis,
)
from sauron.routing.lanes.calendar import route_calendar_events
from sauron.routing.lanes.asks import route_asks
from sauron.routing.lanes.org_intel import route_status_changes, route_org_intelligence
from sauron.routing.lanes.misc import (
    route_standing_offers, route_contact_field_updates,
    route_policy_positions, route_referenced_resources,
)
from sauron.routing.lanes.entity_resolution import (
    _resolve_contact_id_for_entity,
)
from sauron.routing.lanes.signals import (
    _route_provenance, _route_profile_intelligence, _route_affiliations,
    _infer_sentiment, _infer_delta,
)
from sauron.routing.lanes.commitments import (
    _route_standalone_commitments, _collect_scheduling_leads,
)
from sauron.routing.lanes.interaction import (
    route_interaction, route_interaction_participants, route_status_advance,
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════

def route_to_networking_app(
    conversation_id: str,
    extraction: dict,
    networking_app_contact_id: str | None = None,
    is_retry: bool = False,
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
            is_retry=is_retry,
        )
    finally:
        sel_conn.close()


def _execute_routing(
    conversation_id, synthesis, claims,
    networking_app_contact_id, extraction, sel_conn,
    is_retry=False,
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

    # RoutingContext wraps shared mutable state for extracted lane functions.
    _is_solo = synthesis.get("_solo_routing", False)
    _solo_mode = synthesis.get("_solo_mode", "")
    ctx = RoutingContext(
        conversation_id=conversation_id,
        synthesis=synthesis,
        claims=claims,
        networking_app_contact_id=networking_app_contact_id,
        sel_conn=sel_conn,
        is_solo=_is_solo,
        solo_mode=_solo_mode,
        errors=errors,
        secondary_errors=secondary_errors,
        successes=successes,
        core_lane_results=core_lane_results,
        secondary_lane_results=secondary_lane_results,
    )

    # 1/1A/1C. Interaction + participants + status advance
    _created_interaction_id = route_interaction(ctx)

    if _created_interaction_id:
        route_interaction_participants(ctx, _created_interaction_id)

    if _created_interaction_id and networking_app_contact_id:
        route_status_advance(ctx, {
            "sentiment": _infer_sentiment(synthesis),
            "relationshipDelta": _infer_delta(synthesis),
        })
    else:
        # Only log skip when interaction was actually attempted (not solo-skipped)
        _int_status = next(
            (r["status"] for r in core_lane_results if r["name"] == "interaction"),
            None,
        )
        if _int_status not in ("skipped_solo", None):
            secondary_lane_results.append({
                "name": "status_advance",
                "status": "skipped_no_interaction",
            })

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
        ok, err, _resp = _core._api_call(
            "POST", f"{NETWORKING_APP_URL}/api/scheduling-leads", lead_payload
        )
        if ok:
            successes.append(("scheduling_lead", lead_payload))
        else:
            errors.append(("scheduling_lead", lead_payload, err))

    _summarize_lane(ctx, "scheduling_leads", "scheduling_lead", secondary=False)

    # 3. Standing offers (extracted to lanes/misc.py)
    route_standing_offers(ctx)

    _summarize_lane(ctx, "standing_offers", "standing_offer", secondary=False)

    # 4. Follow-ups — routed inline with Interaction (followUpRequired/followUpDescription)
    #    No standalone POST /api/follow-ups needed.

    # 5. Contact field updates (extracted to lanes/misc.py)
    route_contact_field_updates(ctx)

    # 6/7/8. Life events, interests, activities (extracted to lanes/personal.py)
    route_life_events_from_claims(ctx)
    route_interests(ctx)
    route_activities(ctx)

    # 9. Graph edges -> ContactRelationship (extracted to lanes/relationships.py)
    route_graph_edges(ctx)

    _summarize_lane(ctx, "graph_edges", "contact_relationship", secondary=False)

    # 10. Policy positions (extracted to lanes/misc.py)
    route_policy_positions(ctx)

    _summarize_lane(ctx, "policy_positions", "intelligence_signal")

    # 11. Referenced resources (extracted to lanes/misc.py)
    route_referenced_resources(ctx)


    _summarize_lane(ctx, "interests", "interest")

    _summarize_lane(ctx, "activities", "activity")

    _summarize_lane(ctx, "referenced_resources", "referenced_resource")

    # 10b. Status changes (extracted to lanes/org_intel.py)
    route_status_changes(ctx)

    # 10c. Org intelligence (extracted to lanes/org_intel.py)
    route_org_intelligence(ctx)

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

    # 16. Calendar events (extracted to lanes/calendar.py)
    route_calendar_events(ctx)

    _summarize_lane(ctx, "calendar_events", "calendar_event")

    # 17. Asks (extracted to lanes/asks.py)
    route_asks(ctx)

    _summarize_lane(ctx, "asks", "ask_commitment")

    # 18. Life events from synthesis (extracted to lanes/personal.py)
    route_life_events_from_synthesis(ctx)

    _summarize_lane(ctx, "synthesis_life_events", "synthesis_life_event")

    _summarize_lane(ctx, "status_changes", "status_change_signal")

    _summarize_lane(ctx, "org_intelligence", "org_intel_signal")

    _summarize_lane(ctx, "provenance", "provenance")

    _summarize_lane(ctx, "profile_intelligence", "profile_intelligence")

    _summarize_lane(ctx, "affiliations", "affiliation")

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
        # Skip creating new routing_log entry on retry — retry.py manages
        # the original entry's attempts/status. Creating a new entry here
        # caused exponential duplication (each retry spawned a new entry).
        if not is_retry:
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
        _core._store_routing_summary(summary, sel_conn)
        return False

    # All succeeded — log individual successes for audit trail
    # Skip logging on retry to avoid duplicate routing_log entries
    if not is_retry:
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
    _core._store_routing_summary(summary, sel_conn)
    return True
