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
from datetime import datetime

import httpx

from sauron.config import NETWORKING_APP_URL
from sauron.routing.contact_bridge import resolve_networking_contact_id
from sauron.routing.routing_log import (
    log_pending_entity,
    log_routing_failure,
    log_routing_success,
)

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
    errors = []   # [(object_class, payload, error_str)]
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
    else:
        errors.append(("interaction", interaction_payload, err))

    # 2. Scheduling leads (social-firmness commitments + dedicated list)
    for lead_payload in _collect_scheduling_leads(conversation_id, synthesis, networking_app_contact_id, sel_conn):
        ok, err = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/scheduling-leads", lead_payload
        )
        if ok:
            successes.append(("scheduling_lead", lead_payload))
        else:
            errors.append(("scheduling_lead", lead_payload, err))

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
        }
        ok, err = _api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/personal/interests",
            int_payload,
        )
        if ok:
            successes.append(("interest", int_payload))
        else:
            errors.append(("interest", int_payload, err))

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
        }
        ok, err = _api_call(
            "POST",
            f"{NETWORKING_APP_URL}/api/personal/activities",
            act_payload,
        )
        if ok:
            successes.append(("activity", act_payload))
        else:
            errors.append(("activity", act_payload, err))

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
        }
        ok, err = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/signals", sig_payload
        )
        if ok:
            successes.append(("intelligence_signal", sig_payload))
        else:
            errors.append(("intelligence_signal", sig_payload, err))

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
        }
        ok, err = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/referenced-resources", res_payload
        )
        if ok:
            successes.append(("referenced_resource", res_payload))
        else:
            errors.append(("referenced_resource", res_payload, err))

    # 12. New contact stubs for triage (Phase D)
    for name in claims.get("new_contacts_mentioned", []):
        if not name or not isinstance(name, str):
            continue
        name = name.strip()
        if not name:
            continue
        # Only create if we don't already have this person in unified_contacts
        existing_cid = _resolve_contact_id_for_entity(name, None)
        if existing_cid:
            continue  # Already known — skip
        stub_payload = {
            "name": name,
            "source": "sauron",
            "notes": f"Mentioned in conversation {conversation_id[:8]}",
            "status": "new",
            "sourceSystem": "sauron",
            "sourceId": conversation_id,
        }
        ok, err = _api_call(
            "POST", f"{NETWORKING_APP_URL}/api/contacts", stub_payload
        )
        if ok:
            successes.append(("new_contact_stub", stub_payload))
        else:
            errors.append(("new_contact_stub", stub_payload, err))

    # ── All-or-nothing verdict ──────────────────────────────────
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
        return False

    # All succeeded — log individual successes for audit trail
    for obj_class, payload in successes:
        log_routing_success(conversation_id, obj_class, payload)
    logger.info(
        f"Routed conversation {conversation_id[:8]} — "
        f"{len(successes)} object(s) sent successfully"
    )
    return True


# ═══════════════════════════════════════════════════════════════
# Payload builders
# ═══════════════════════════════════════════════════════════════

def _collect_inline_commitments(synthesis: dict) -> list[dict]:
    """Build commitments array for inline inclusion in Interaction payload.

    Non-social, non-tentative commitments from both my_commitments and
    contact_commitments. Social → scheduling_leads. Tentative → skipped.

    The Networking App POST /api/interactions creates Commitment rows
    with interactionId automatically from this array.
    """
    inline = []
    for source_list, direction in [
        (synthesis.get("my_commitments", []), "i_owe"),
        (synthesis.get("contact_commitments", []), "they_owe"),
    ]:
        for c in source_list:
            firmness = c.get("firmness", "intentional")
            if firmness in ("social", "tentative"):
                continue
            # Map direction to Networking App prefix
            prefix = "[Mine]" if direction in ("i_owe", "owed_by_me") else "[Theirs]"
            inline.append({
                "description": f"{prefix} {c.get('description', '')}",
                "dueDate": c.get("resolved_date") or c.get("due_date") or c.get("dueDate"),
                "sourceClaimId": c.get("source_claim_id"),
            })
    return inline


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
