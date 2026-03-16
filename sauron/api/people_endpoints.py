"""People-related conversation endpoints (extracted from conversations.py)."""

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()



def _resolve_graph_entity(conn, conversation_id: str, original_name: str,
                          entity_id: str, canonical_name: str, source: str = "user"):
    """Link a graph-edge-only person to a contact.

    1. Insert synthesis_entity_links sentinel so the people panel sees it.
    2. Update graph_edges text so the graph panel shows the canonical name.
    """
    import uuid as _uuid

    orig_stripped = original_name.strip()
    orig_lower = orig_stripped.lower()

    # 1. Sentinel: only if no existing link for this specific name
    existing = conn.execute("""
        SELECT 1 FROM synthesis_entity_links
        WHERE conversation_id = ?
          AND LOWER(TRIM(original_name)) = ?
          AND resolved_entity_id = ?
        LIMIT 1
    """, (conversation_id, orig_lower, entity_id)).fetchone()

    existing_claim = conn.execute("""
        SELECT 1 FROM event_claims
        WHERE conversation_id = ?
          AND LOWER(TRIM(subject_name)) = ?
          AND subject_entity_id = ?
        LIMIT 1
    """, (conversation_id, orig_lower, entity_id)).fetchone()

    if not existing and not existing_claim:
        conn.execute("""
            INSERT INTO synthesis_entity_links
                (id, conversation_id, object_type, object_index, field_name,
                 original_name, resolved_entity_id, link_source, confidence)
            VALUES (?, ?, 'graph_entity', 0, 'entity', ?, ?, ?, 1.0)
        """, (str(_uuid.uuid4()), conversation_id,
              orig_stripped, entity_id, source))
        logger.info("[RESOLVE] Sentinel: %s -> %s in %s",
                    orig_stripped, canonical_name, conversation_id[:8])

    # 2. Update graph_edges text to canonical name
    if orig_lower != canonical_name.strip().lower():
        updated_from = conn.execute("""
            UPDATE graph_edges SET from_entity = ?
            WHERE source_conversation_id = ?
              AND LOWER(TRIM(from_entity)) = ?
        """, (canonical_name, conversation_id, orig_lower)).rowcount

        updated_to = conn.execute("""
            UPDATE graph_edges SET to_entity = ?
            WHERE source_conversation_id = ?
              AND LOWER(TRIM(to_entity)) = ?
        """, (canonical_name, conversation_id, orig_lower)).rowcount

        if updated_from or updated_to:
            logger.info("[RESOLVE] Graph edges: '%s' -> '%s' (%d from, %d to) in %s",
                        orig_stripped, canonical_name,
                        updated_from, updated_to, conversation_id[:8])


SELF_ENTITY_ID = "948c2cf3-9a8c-49d5-853c-d54e91b7133a"

# Singular→plural mapping for synthesis object types
_OBJ_TYPE_PLURAL = {
    "standing_offer": "standing_offers",
    "scheduling_lead": "scheduling_leads",
    "graph_edge": "graph_edges",
    "new_contact": "new_contacts_mentioned",
}
_OBJ_TYPE_SINGULAR = {v: k for k, v in _OBJ_TYPE_PLURAL.items()}


class ConfirmPersonRequest(BaseModel):
    original_name: str
    entity_id: str


class LinkRemainingRequest(BaseModel):
    entity_id: str
    subject_name: str


class SkipPersonRequest(BaseModel):
    original_name: str
    entity_id: Optional[str] = None


@router.get("/{conversation_id}/people")
def list_conversation_people(conversation_id: str):
    """List all people referenced in a conversation with resolution status.

    Returns each unique person with:
    - status: confirmed (green), auto_resolved (yellow), provisional (red), unresolved (red)
    - is_self: True if this is Stephen Andrews
    - claim_count, roles, link_sources
    """
    conn = get_connection()
    try:
        people_map = {}  # key: entity_id or "unresolved:<lowername>"

        # ── Source 1: Subject references from event_claims ──
        subjects = conn.execute("""
            SELECT ec.subject_name, ec.subject_entity_id,
                   uc.canonical_name, uc.is_confirmed
            FROM event_claims ec
            LEFT JOIN unified_contacts uc ON uc.id = ec.subject_entity_id
            WHERE ec.conversation_id = ?
              AND ec.subject_name IS NOT NULL
              AND (ec.review_status IS NULL OR ec.review_status != 'dismissed')
        """, (conversation_id,)).fetchall()

        for s in subjects:
            entity_id = s["subject_entity_id"]
            name = s["subject_name"]
            key = entity_id if entity_id else f"unresolved:{name.strip().lower()}"

            if key not in people_map:
                people_map[key] = {
                    "original_names": set(),
                    "entity_id": entity_id,
                    "canonical_name": s["canonical_name"],
                    "is_confirmed": s["is_confirmed"],
                    "subject_claim_count": 0,
                    "roles": set(),
                    "link_sources": set(),
                }
            people_map[key]["original_names"].add(name)
            people_map[key]["subject_claim_count"] += 1
            people_map[key]["roles"].add("subject")

        # ── Source 2: claim_entities (subject + target roles) ──
        ce_rows = conn.execute("""
            SELECT ce.entity_name, ce.entity_id, ce.role, ce.link_source,
                   uc.canonical_name, uc.is_confirmed
            FROM claim_entities ce
            JOIN event_claims ec ON ec.id = ce.claim_id
            LEFT JOIN unified_contacts uc ON uc.id = ce.entity_id
            WHERE ec.conversation_id = ?
              AND (ec.review_status IS NULL OR ec.review_status != 'dismissed')
              AND (ce.entity_table = 'unified_contacts' OR ce.entity_table IS NULL)
        """, (conversation_id,)).fetchall()

        for ce in ce_rows:
            entity_id = ce["entity_id"]
            name = ce["entity_name"]
            key = entity_id if entity_id else f"unresolved:{name.strip().lower()}"

            if key not in people_map:
                people_map[key] = {
                    "original_names": set(),
                    "entity_id": entity_id,
                    "canonical_name": ce["canonical_name"],
                    "is_confirmed": ce["is_confirmed"],
                    "subject_claim_count": 0,
                    "roles": set(),
                    "link_sources": set(),
                }
            people_map[key]["original_names"].add(name)
            people_map[key]["roles"].add(ce["role"])
            if ce["link_source"]:
                people_map[key]["link_sources"].add(ce["link_source"])
            # Update canonical/confirmed if we got better data
            if entity_id and ce["canonical_name"] and not people_map[key]["canonical_name"]:
                people_map[key]["canonical_name"] = ce["canonical_name"]
                people_map[key]["is_confirmed"] = ce["is_confirmed"]

        # ── Source 3: synthesis_entity_links ──
        sel_rows = conn.execute("""
            SELECT sel.original_name, sel.resolved_entity_id, sel.link_source,
                   sel.confidence, uc.canonical_name, uc.is_confirmed
            FROM synthesis_entity_links sel
            LEFT JOIN unified_contacts uc ON uc.id = sel.resolved_entity_id
            WHERE sel.conversation_id = ?
        """, (conversation_id,)).fetchall()

        for sel in sel_rows:
            entity_id = sel["resolved_entity_id"]
            name = sel["original_name"]
            key = entity_id if entity_id else f"unresolved:{name.strip().lower()}"

            if key not in people_map:
                people_map[key] = {
                    "original_names": set(),
                    "entity_id": entity_id,
                    "canonical_name": sel["canonical_name"],
                    "is_confirmed": sel["is_confirmed"],
                    "subject_claim_count": 0,
                    "roles": set(),
                    "link_sources": set(),
                }
            people_map[key]["original_names"].add(name)
            if sel["link_source"]:
                people_map[key]["link_sources"].add(sel["link_source"])

        # ── Source 4: graph_edges (person-typed entities) ──
        # Surface people referenced in graph edges that weren't caught by claims/synthesis
        # Wrapped in try/except: graph_edges enrichment is supplementary and must not
        # crash the /people endpoint if schema columns (from_type, to_type) are missing.
        ge_rows = []
        try:
            PERSON_EDGE_TYPES = {
                "reports_to", "works_with", "knows", "supports", "opposes",
                "mentors", "manages", "advises",
            }
            ge_rows = conn.execute("""
                SELECT from_entity, from_type, to_entity, to_type, edge_type
                FROM graph_edges
                WHERE source_conversation_id = ?
            """, (conversation_id,)).fetchall()
        except Exception as e:
            logger.warning(
                "[PEOPLE] conversation=%s: graph-edge enrichment skipped — %s",
                conversation_id, e,
            )

        for ge in ge_rows:
            # Check from_entity
            if ge["from_type"] == "person" or ge["edge_type"] in PERSON_EDGE_TYPES:
                name = ge["from_entity"]
                if name and name.strip():
                    key = f"unresolved:{name.strip().lower()}"
                    # Only add if not already captured by another source
                    # Check both unresolved key and resolved entries
                    already_known = key in people_map or any(
                        name.strip().lower() in {n.strip().lower() for n in d["original_names"]}
                        for d in people_map.values()
                    )
                    if not already_known:
                        people_map[key] = {
                            "original_names": {name.strip()},
                            "entity_id": None,
                            "canonical_name": None,
                            "is_confirmed": None,
                            "subject_claim_count": 0,
                            "roles": {"graph_entity"},
                            "link_sources": set(),
                        }

            # Check to_entity
            if ge["to_type"] == "person" or ge["edge_type"] in PERSON_EDGE_TYPES:
                name = ge["to_entity"]
                if name and name.strip():
                    key = f"unresolved:{name.strip().lower()}"
                    already_known = key in people_map or any(
                        name.strip().lower() in {n.strip().lower() for n in d["original_names"]}
                        for d in people_map.values()
                    )
                    if not already_known:
                        people_map[key] = {
                            "original_names": {name.strip()},
                            "entity_id": None,
                            "canonical_name": None,
                            "is_confirmed": None,
                            "subject_claim_count": 0,
                            "roles": {"graph_entity"},
                            "link_sources": set(),
                        }

                # ── Consolidate: merge unresolved into matching resolved person ──
        # If "unresolved:daniel park" exists AND a resolved entity has
        # canonical_name "Daniel Park" (case-insensitive), merge claims into
        # the resolved entry. Display-only — no DB mutation.
        resolved_by_name = {}  # lowered canonical_name -> key
        resolved_all_names = {}  # every name variant -> key
        for key, data in people_map.items():
            if data["entity_id"] and data["canonical_name"]:
                cn = data["canonical_name"].strip().lower()
                resolved_by_name[cn] = key
                resolved_all_names[cn] = key
                for oname in data["original_names"]:
                    resolved_all_names[oname.strip().lower()] = key
                # Also load aliases from unified_contacts
                try:
                    alias_row = conn.execute(
                        "SELECT aliases FROM unified_contacts WHERE id = ?",
                        (data["entity_id"],),
                    ).fetchone()
                    if alias_row and alias_row["aliases"]:
                        raw = alias_row["aliases"]
                        # Handle semicolon-separated or JSON array
                        if raw.startswith("["):
                            import json as _json
                            alias_list = _json.loads(raw)
                        else:
                            alias_list = [a.strip() for a in raw.split(";") if a.strip()]
                        for alias in alias_list:
                            resolved_all_names[alias.strip().lower()] = key
                except Exception:
                    pass

        unresolved_keys = [k for k in people_map if k.startswith("unresolved:")]
        for ukey in unresolved_keys:
            udata = people_map[ukey]
            # Check each original_name against resolved canonical + alias names
            for uname in list(udata["original_names"]):
                match_key = resolved_all_names.get(uname.strip().lower())
                if match_key and match_key in people_map:
                    # Merge into resolved entry
                    rdata = people_map[match_key]
                    rdata["original_names"] |= udata["original_names"]
                    rdata["subject_claim_count"] += udata["subject_claim_count"]
                    rdata["unlinked_claim_count"] = rdata.get("unlinked_claim_count", 0) + udata["subject_claim_count"]
                    rdata["roles"] |= udata["roles"]
                    rdata["link_sources"] |= udata["link_sources"]
                    del people_map[ukey]
                    break  # This unresolved key is consumed

        # ── Build response ──
        people = []
        for key, data in people_map.items():
            entity_id = data["entity_id"]
            link_sources = data["link_sources"]
            is_confirmed = data["is_confirmed"]

            # Determine status
            if "skipped" in link_sources:
                status = "skipped"
            elif "dismissed" in link_sources:
                status = "dismissed"
            elif entity_id is None:
                status = "unresolved"
            elif is_confirmed == 0:
                status = "provisional"
            elif is_confirmed == 1:
                status = "confirmed"
            elif link_sources & {"user", "speaker_cascade", "confirm_person", "bulk_reassign"}:
                status = "confirmed"
            else:
                status = "auto_resolved"

            people.append({
                "original_name": sorted(data["original_names"])[0],
                "all_names": sorted(data["original_names"]),
                "entity_id": entity_id,
                "canonical_name": data["canonical_name"],
                "status": status,
                "is_self": entity_id == SELF_ENTITY_ID,
                "is_provisional": is_confirmed == 0 if entity_id else False,
                "claim_count": data["subject_claim_count"],
                "unlinked_claim_count": data.get("unlinked_claim_count", 0),
                "roles": sorted(data["roles"]),
                "link_sources": sorted(data["link_sources"]),
            })

        # Sort: unresolved first, then provisional, auto_resolved, confirmed
        status_order = {"unresolved": 0, "provisional": 1, "auto_resolved": 2, "confirmed": 3, "skipped": 4}
        people.sort(key=lambda p: (status_order.get(p["status"], 99), p["original_name"]))

        return {"people": people, "total": len(people)}
    finally:
        conn.close()


@router.post("/{conversation_id}/confirm-person")
def confirm_person(conversation_id: str, request: ConfirmPersonRequest):
    """Confirm an auto-resolved person mapping (yellow -> green).

    Only for already-resolved people. Provisional contacts use
    graph.py endpoints (link_provisional_to_existing, confirm_provisional_contact).
    """
    conn = get_connection()
    try:
        # Verify entity is a confirmed contact (not provisional)
        contact = conn.execute(
            "SELECT id, canonical_name, is_confirmed FROM unified_contacts WHERE id = ?",
            (request.entity_id,),
        ).fetchone()

        if not contact:
            raise HTTPException(404, "Contact not found")
        if not contact["is_confirmed"]:
            raise HTTPException(
                400,
                "Contact is provisional. Use /api/graph/provisional/{id}/link "
                "or /api/graph/provisional/{id}/confirm instead.",
            )

        canonical_name = contact["canonical_name"]

        # Collect all original names for this entity in this conversation
        original_names = {request.original_name}

        # From event_claims
        claims = conn.execute("""
            SELECT DISTINCT subject_name FROM event_claims
            WHERE conversation_id = ? AND subject_entity_id = ?
              AND subject_name IS NOT NULL
        """, (conversation_id, request.entity_id)).fetchall()
        for c in claims:
            original_names.add(c["subject_name"])

        # From synthesis_entity_links
        sel_names = conn.execute("""
            SELECT DISTINCT original_name FROM synthesis_entity_links
            WHERE conversation_id = ? AND resolved_entity_id = ?
        """, (conversation_id, request.entity_id)).fetchall()
        for s in sel_names:
            original_names.add(s["original_name"])

        # Run cascade
        from sauron.extraction.cascade import cascade_entity_confirmation
        cascade_stats = cascade_entity_confirmation(
            conn, request.entity_id, canonical_name,
            list(original_names), conversation_id,
            source="confirm_person",
        )

        # Ensure claim_entities rows exist for all claims already linked via subject_entity_id.
        # The cascade only creates junction rows for NEW links; claims that were linked
        # (e.g., by manual fix or prior cascade) but lack claim_entities rows need backfill.
        from sauron.api.corrections import sync_claim_entities_subject
        linked_claims = conn.execute("""
            SELECT ec.id FROM event_claims ec
            WHERE ec.conversation_id = ? AND ec.subject_entity_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM claim_entities ce
                  WHERE ce.claim_id = ec.id AND ce.entity_id = ?
              )
        """, (conversation_id, request.entity_id, request.entity_id)).fetchall()
        for lc in linked_claims:
            sync_claim_entities_subject(
                conn, lc["id"], request.entity_id, canonical_name, "confirm_person"
            )

        # Upgrade link_source from auto -> user for claim_entities in this conversation
        conn.execute("""
            UPDATE claim_entities SET link_source = 'user'
            WHERE entity_id = ?
              AND link_source IN ('auto_synthesis', 'resolver', 'model', 'confirm_person', 'cascade')
              AND claim_id IN (
                  SELECT id FROM event_claims WHERE conversation_id = ?
              )
        """, (request.entity_id, conversation_id))

        # Also upgrade synthesis_entity_links (including overriding 'skipped')
        conn.execute("""
            UPDATE synthesis_entity_links SET link_source = 'user'
            WHERE resolved_entity_id = ?
              AND conversation_id = ?
              AND link_source != 'user'
        """, (request.entity_id, conversation_id))

        # Resolve graph-entity-only people: sentinel + graph_edges text update
        _resolve_graph_entity(
            conn, conversation_id, request.original_name,
            request.entity_id, canonical_name, source="confirm_person",
        )
        conn.commit()
        return {
            "status": "ok",
            "confirmed": canonical_name,
            "entity_id": request.entity_id,
            "cascade": cascade_stats,
        }
    finally:
        conn.close()


@router.post("/{conversation_id}/link-remaining-claims")
def link_remaining_claims(conversation_id: str, request: LinkRemainingRequest):
    """Link orphaned claims to a confirmed entity by exact name match.

    For claims where subject_name matches but subject_entity_id is NULL.
    Does not overwrite existing links. Does not touch dismissed claims.
    Requires the entity to be a confirmed contact.
    """
    conn = get_connection()
    try:
        # Verify entity is confirmed
        contact = conn.execute(
            "SELECT id, canonical_name, is_confirmed FROM unified_contacts WHERE id = ?",
            (request.entity_id,),
        ).fetchone()
        if not contact:
            raise HTTPException(404, "Contact not found")
        if not contact["is_confirmed"]:
            raise HTTPException(400, "Contact is not confirmed")

        canonical_name = contact["canonical_name"]

        # Find orphaned claims: same conversation, exact name match, NULL entity, not dismissed
        orphans = conn.execute(
            """SELECT id, subject_name FROM event_claims
               WHERE conversation_id = ?
                 AND LOWER(TRIM(subject_name)) = LOWER(TRIM(?))
                 AND subject_entity_id IS NULL
                 AND (review_status IS NULL OR review_status != 'dismissed')""",
            (conversation_id, request.subject_name),
        ).fetchall()

        if not orphans:
            return {"linked": 0, "entity_id": request.entity_id}

        from sauron.api.corrections import sync_claim_entities_subject

        linked = 0
        for orphan in orphans:
            try:
                sync_claim_entities_subject(
                    conn, orphan["id"], request.entity_id,
                    canonical_name, "user_link_remaining",
                )
                linked += 1
            except Exception:
                logger.exception(f"link-remaining failed for claim {orphan['id'][:8]}")

        conn.commit()
        return {"linked": linked, "entity_id": request.entity_id, "canonical_name": canonical_name}
    finally:
        conn.close()


@router.post("/{conversation_id}/skip-person")
def skip_person(conversation_id: str, request: SkipPersonRequest):
    """Mark a person as skipped - don't prompt for review again."""
    conn = get_connection()
    try:
        updated = 0

        # Update synthesis_entity_links by name
        updated += conn.execute("""
            UPDATE synthesis_entity_links SET link_source = 'skipped'
            WHERE conversation_id = ?
              AND LOWER(TRIM(original_name)) = LOWER(?)
              AND link_source != 'skipped'
        """, (conversation_id, request.original_name.strip())).rowcount

        # If entity_id provided, also skip by entity_id
        if request.entity_id:
            updated += conn.execute("""
                UPDATE synthesis_entity_links SET link_source = 'skipped'
                WHERE conversation_id = ?
                  AND resolved_entity_id = ?
                  AND link_source != 'skipped'
            """, (conversation_id, request.entity_id)).rowcount

        # If no rows were updated, this person has no synthesis_entity_links rows
        # (e.g. unresolved people only referenced in claims). Insert a skipped row.
        if updated == 0:
            import uuid as _uuid
            conn.execute("""
                INSERT INTO synthesis_entity_links
                    (id, conversation_id, object_type, object_index, field_name,
                     original_name, resolved_entity_id, link_source, confidence)
                VALUES (?, ?, '_skip', 0, '_skip', ?, ?, 'skipped', 0.0)
            """, (str(_uuid.uuid4()), conversation_id, request.original_name.strip(),
                  request.entity_id))
            updated = 1

        conn.commit()
        return {
            "status": "ok",
            "skipped_name": request.original_name,
            "links_updated": updated,
        }
    finally:
        conn.close()


@router.post("/{conversation_id}/unskip-person")
def unskip_person(conversation_id: str, request: SkipPersonRequest):
    """Revert a skipped person back to their pre-skip state."""
    conn = get_connection()
    try:
        updated = 0

        # Revert synthesis_entity_links by name
        updated += conn.execute("""
            UPDATE synthesis_entity_links SET link_source = 'auto_synthesis'
            WHERE conversation_id = ?
              AND LOWER(TRIM(original_name)) = LOWER(?)
              AND link_source IN ('skipped', 'dismissed')
        """, (conversation_id, request.original_name.strip())).rowcount

        # If entity_id provided, also revert by entity_id
        if request.entity_id:
            updated += conn.execute("""
                UPDATE synthesis_entity_links SET link_source = 'auto_synthesis'
                WHERE conversation_id = ?
                  AND resolved_entity_id = ?
                  AND link_source IN ('skipped', 'dismissed')
            """, (conversation_id, request.entity_id)).rowcount

        conn.commit()
        return {
            "status": "ok",
            "unskipped_name": request.original_name,
            "links_updated": updated,
        }
    finally:
        conn.close()


@router.post("/{conversation_id}/dismiss-person")
def dismiss_person(conversation_id: str, request: SkipPersonRequest):
    """Dismiss a person from this conversation's review.

    Works for both resolved and unresolved people. Inserts/updates
    synthesis_entity_links with link_source='dismissed'.
    """
    import uuid as _uuid
    conn = get_connection()
    try:
        updated = 0

        # Try UPDATE existing rows first
        updated += conn.execute("""
            UPDATE synthesis_entity_links SET link_source = 'dismissed'
            WHERE conversation_id = ?
              AND LOWER(TRIM(original_name)) = LOWER(?)
              AND link_source != 'dismissed'
        """, (conversation_id, request.original_name.strip())).rowcount

        if request.entity_id:
            updated += conn.execute("""
                UPDATE synthesis_entity_links SET link_source = 'dismissed'
                WHERE conversation_id = ?
                  AND resolved_entity_id = ?
                  AND link_source != 'dismissed'
            """, (conversation_id, request.entity_id)).rowcount

        # If no rows existed, insert a dismissed sentinel row
        if updated == 0:
            conn.execute("""
                INSERT INTO synthesis_entity_links
                    (id, conversation_id, object_type, object_index, field_name,
                     original_name, resolved_entity_id, link_source, confidence)
                VALUES (?, ?, '_skip', 0, '_skip', ?, ?, 'dismissed', 0.0)
            """, (str(_uuid.uuid4()), conversation_id, request.original_name.strip(),
                  request.entity_id))
            updated = 1

        conn.commit()
        return {
            "status": "ok",
            "dismissed_name": request.original_name,
            "links_updated": updated,
        }
    finally:
        conn.close()



@router.get("/{conversation_id}/entities")
def get_conversation_entities(conversation_id: str):
    """Get non-person entities referenced in this conversation."""
    conn = get_connection()
    try:
        # Source 1: claim_entities with entity_table='unified_entities'
        ce_rows = conn.execute("""
            SELECT DISTINCT ue.id, ue.entity_type, ue.canonical_name, ue.aliases,
                   ue.is_confirmed, ue.observation_count, ue.description
            FROM claim_entities ce
            JOIN event_claims ec ON ec.id = ce.claim_id
            JOIN unified_entities ue ON ue.id = ce.entity_id
            WHERE ec.conversation_id = ?
              AND ce.entity_table = 'unified_entities'
              AND (ec.review_status IS NULL OR ec.review_status != 'dismissed')
        """, (conversation_id,)).fetchall()

        entities_map = {}
        for row in ce_rows:
            d = dict(row)
            entities_map[d["id"]] = d

        # Source 2: graph_edges with entity references
        ge_rows = conn.execute("""
            SELECT DISTINCT ue.id, ue.entity_type, ue.canonical_name, ue.aliases,
                   ue.is_confirmed, ue.observation_count, ue.description
            FROM graph_edges ge
            JOIN unified_entities ue
              ON (ue.id = ge.from_entity_id AND ge.from_entity_table = 'unified_entities')
              OR (ue.id = ge.to_entity_id AND ge.to_entity_table = 'unified_entities')
            WHERE ge.source_conversation_id = ?
        """, (conversation_id,)).fetchall()

        for row in ge_rows:
            d = dict(row)
            if d["id"] not in entities_map:
                entities_map[d["id"]] = d

        # Source 3: Non-person entities from graph_edges, matched by name or shown as provisional
        ge_name_rows = conn.execute("""
            SELECT DISTINCT ge_name, ge_type FROM (
                SELECT ge.from_entity AS ge_name, ge.from_type AS ge_type
                FROM graph_edges ge
                WHERE ge.source_conversation_id = ?
                  AND ge.from_type IS NOT NULL AND ge.from_type != 'person'
                UNION
                SELECT ge.to_entity AS ge_name, ge.to_type AS ge_type
                FROM graph_edges ge
                WHERE ge.source_conversation_id = ?
                  AND ge.to_type IS NOT NULL AND ge.to_type != 'person'
            )
        """, (conversation_id, conversation_id)).fetchall()

        seen_names = {e.get("canonical_name", "").lower() for e in entities_map.values()}
        for ge_row in ge_name_rows:
            name = (ge_row["ge_name"] or "").strip()
            if not name or name.lower() in seen_names:
                continue
            # Try to match against unified_entities by canonical_name or alias
            ue_row = conn.execute("""
                SELECT id, entity_type, canonical_name, aliases,
                       is_confirmed, observation_count, description
                FROM unified_entities
                WHERE LOWER(canonical_name) = LOWER(?)
                LIMIT 1
            """, (name,)).fetchone()
            if ue_row:
                d = dict(ue_row)
                if d["id"] not in entities_map:
                    entities_map[d["id"]] = d
                    seen_names.add(d["canonical_name"].lower())
            else:
                # Surface as a virtual provisional entry (no DB row yet)
                virtual_id = f"ge:{name}"
                entities_map[virtual_id] = {
                    "id": virtual_id,
                    "entity_type": ge_row["ge_type"] or "organization",
                    "canonical_name": name,
                    "aliases": None,
                    "is_confirmed": 0,
                    "observation_count": 1,
                    "description": None,
                    "source": "graph_edge",
                }
                seen_names.add(name.lower())

        return list(entities_map.values())
    finally:
        conn.close()
