"""Signal routing lanes — provenance, profile intelligence, affiliations, sentiment/delta.

Extracted from networking.py (Wave 2) as a behavior-preserving code move.
These are all "signal" lanes that share the resolve-build-post-tally pattern
and route to signal-type endpoints.
"""

import logging

import httpx
from sauron.config import NETWORKING_APP_URL
from sauron.routing.provisional import store_provisional_org
from sauron.routing.routing_log import (
    log_pending_entity,
    log_routing_failure,
    log_routing_success,
)

from sauron.routing.lanes.core import (
    TIMEOUT, _api_call,
)
from sauron.routing.lanes.entity_resolution import (
    _resolve_contact_id_for_entity, _resolve_with_synthesis_links,
    _find_provisional_entity_id, _hold_pending_route, _SKIP_SENTINEL,
)

logger = logging.getLogger(__name__)


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

        ok, err, _resp = _api_call(
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
            ok, err, _resp = _api_call(
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
        ok, err, _resp = _api_call(
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
        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/contact-profile-signals", payload
        )
        if ok:
            successes.append(("vocal_summary", payload))
        else:
            sec_errors.append(("vocal_summary", payload, err))

    return successes, sec_errors

def _route_affiliations(
    conversation_id: str,
    synthesis: dict,
    networking_app_contact_id: str | None,
    sel_conn=None,
) -> tuple[list[tuple], list[tuple]]:
    """Lane 15 (Wave 2): Route affiliation mentions to Networking App.

    Sends organizationName (not ID) -- Networking's orgResolver handles resolution.
    contactId resolved via synthesis_entity_links or fallback to primary contact.
    Dedup by provenance triple (sourceSystem + sourceId + sourceClaimId).
    resolutionSource from org resolution persists on resulting ContactAffiliation.

    Secondary lane -- non-fatal.
    """
    successes = []
    sec_errors = []

    for idx, aff in enumerate(synthesis.get("affiliation_mentions", [])):
        contact_name = aff.get("contact_name", "")
        org_name = aff.get("organization", "")
        if not contact_name or not org_name:
            continue

        # Resolve contact ID
        if sel_conn is not None:
            cid = _resolve_with_synthesis_links(
                sel_conn, conversation_id, "affiliation_mention", idx,
                "contact_name", contact_name, networking_app_contact_id,
            )
            if cid == _SKIP_SENTINEL:
                logger.debug(f"Skipping affiliation[{idx}]: person marked as skipped")
                continue
        else:
            cid = _resolve_contact_id_for_entity(
                contact_name, networking_app_contact_id
            )

        if not cid:
            # Hold for pending entity if provisional
            if sel_conn:
                blocked = _find_provisional_entity_id(sel_conn, contact_name)
                if blocked:
                    _hold_pending_route(
                        sel_conn, conversation_id, "affiliation",
                        aff, blocked,
                    )
                    logger.info(f"Held affiliation[{idx}]: blocked on {blocked[:8]}")
            continue

        payload = {
            "contactId": cid,
            "organizationName": org_name,  # Networking resolves via orgResolver
            "title": aff.get("title"),
            "department": aff.get("department"),
            "roleType": aff.get("role_type"),  # open-ended, not enum-restricted
            "isCurrent": aff.get("is_current", True),
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
            "sourceClaimId": aff.get("source_claim_id"),
        }

        ok, err, _resp = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/contact-affiliations", payload
        )
        if ok:
            successes.append(("affiliation", payload))
        else:
            # Capture provisional org suggestion on 422 (org not resolved)
            if _resp and _resp.get("resolutionSource") == "provisional_suggestion":
                store_provisional_org(
                    raw_name=org_name,
                    normalized_name=org_name.lower().strip(),
                    conversation_id=conversation_id,
                    source_context=f"affiliation: {contact_name} at {org_name} ({aff.get('title', '')})",
                    resolution_source_context="provisional_suggestion",
                    suggested_by="affiliation",
                )
            elif err and "422" in err and "not resolved" in err.lower():
                store_provisional_org(
                    raw_name=org_name,
                    normalized_name=org_name.lower().strip(),
                    conversation_id=conversation_id,
                    source_context=f"affiliation: {contact_name} at {org_name} ({aff.get('title', '')})",
                    resolution_source_context=err[:200],
                    suggested_by="affiliation",
                )
            sec_errors.append(("affiliation", payload, err))

    return successes, sec_errors


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
