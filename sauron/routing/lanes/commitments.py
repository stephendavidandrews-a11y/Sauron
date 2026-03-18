"""Commitment and action routing lanes — inline commitments, standalone commitments,
scheduling leads, interaction participants, and contact field patching.

Extracted from networking.py (Wave 2) as a behavior-preserving code move.
These are "action/commitment" lanes — things people agreed to do, scheduling leads,
participants, and contact field patching.
"""

import logging

import httpx
from sauron.config import NETWORKING_APP_URL
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
    _SKIP_SENTINEL,
)

logger = logging.getLogger(__name__)


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

            ok, err, _resp = _api_call(
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
            "sourceClaimId": lead.get("source_claim_id"),
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
                    "sourceClaimId": c.get("source_claim_id"),
                })

    return leads


def _route_interaction_participants(
    interaction_id: str,
    conversation_id: str,
    primary_contact_id: str | None,
    sel_conn,
):
    """Route interaction participants from speaker diarization.

    Looks up speaker→contact mappings from unified_contacts (voice enrollment),
    then POSTs each resolved speaker as an InteractionParticipant.

    Does NOT create participants for unresolved speakers — skip over noise.
    The primary contact (from interaction.contactId) is always added as
    a participant with role=participant if resolved.
    """
    from sauron.db.connection import get_connection

    # Collect speaker→contact mappings from the conversation
    conn = get_connection()
    try:
        speaker_rows = conn.execute(
            """SELECT DISTINCT t.speaker_label, uc.networking_app_contact_id, uc.canonical_name
               FROM transcripts t
               JOIN voice_match_log vml ON vml.conversation_id = t.conversation_id
                   AND vml.speaker_label = t.speaker_label
               JOIN voice_profiles vp ON vp.id = vml.matched_profile_id
               JOIN unified_contacts uc ON uc.id = vp.contact_id
               WHERE t.conversation_id = ?
                 AND uc.networking_app_contact_id IS NOT NULL""",
            (conversation_id,),
        ).fetchall()
    finally:
        conn.close()

    # Always include primary contact as participant
    posted_contact_ids = set()
    if primary_contact_id:
        p_ok, _, _ = _api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/interaction-participants",
            {
                "interactionId": interaction_id,
                "contactId": primary_contact_id,
                "role": "participant",
                "sourceSystem": "sauron",
                "sourceId": conversation_id,
                "sourceClaimId": f"participant:primary:{primary_contact_id}",
            },
        )
        if p_ok:
            posted_contact_ids.add(primary_contact_id)
            logger.debug(f"Added primary contact as participant: {primary_contact_id[:8]}")

    # Add other resolved speakers
    for row in speaker_rows:
        cid = row["networking_app_contact_id"]
        if cid in posted_contact_ids:
            continue
        p_ok, _, _ = _api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/interaction-participants",
            {
                "interactionId": interaction_id,
                "contactId": cid,
                "role": "participant",
                "speakerLabel": row["speaker_label"],
                "sourceSystem": "sauron",
                "sourceId": conversation_id,
                "sourceClaimId": f"participant:{row['speaker_label']}:{cid}",
            },
        )
        if p_ok:
            posted_contact_ids.add(cid)
            logger.debug(
                f"Added speaker {row['speaker_label']} ({row['canonical_name']}) "
                f"as participant: {cid[:8]}"
            )

    if posted_contact_ids:
        logger.info(
            f"Routed {len(posted_contact_ids)} interaction participants "
            f"for interaction {interaction_id[:8]}"
        )


def _update_contact_field_null_only(
    memory_write: dict, fallback_contact_id: str | None
) -> tuple[bool | None, str | None]:
    """Update a contact field only if the current value is null.

    Phase C: Fetches the contact first and checks whether the target
    field already has a non-null/non-empty value. If it does, the
    update is skipped to avoid overwriting user-curated data.

    Uses PATCH (partial update) to set only the target field without
    affecting other contact fields.

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
    url = f"{NETWORKING_APP_URL}/api/contacts/{contact_id}"
    ok, err, body = _api_call("GET", url, {})
    if not ok:
        return False, f"GET contact {contact_id[:8]} failed: {err}"
    contact = body

    # Null-only check: skip if field already has a value
    current = contact.get(net_field)
    if current is not None and str(current).strip() != "":
        logger.debug(
            f"Skipping {entity_name}.{net_field} — already has value"
        )
        return None, None

    # PATCH: send only the field we want to update.
    # The Networking App now supports PATCH /api/contacts/[id] which
    # updates only provided fields without wiping unspecified ones.
    #
    # SCOPE: PATCH is for lightweight flat-field enrichment only
    # (title, organization, email, phone, social links, etc.).
    # Structured role/affiliation changes must go through the
    # ContactAffiliation lane, not direct contact patching.
    ok, err, _resp = _api_call(
        "PATCH",
        f"{NETWORKING_APP_URL}/api/contacts/{contact_id}",
        {net_field: value},
    )
    if ok:
        logger.info(f"Updated {entity_name}.{net_field} (was null)")
    return ok, err
