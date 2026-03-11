"""Sync contacts from the Networking App into Sauron's unified_contacts.

Pulls contact data, relationship labels, and builds relational aliases
so that casual references ("my brother", "his wife") can be auto-resolved.
"""

import json
import logging
import uuid

import httpx

from sauron.config import NETWORKING_APP_URL
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=5.0)

# Relational terms for building aliases
RELATION_LABELS = {
    "partner", "spouse", "wife", "husband", "brother", "sister",
    "mom", "mother", "dad", "father", "son", "daughter",
    "boss", "assistant", "colleague", "friend",
}


def sync_contacts_from_networking_app() -> dict:
    """Pull contacts from Networking App and sync to unified_contacts.

    Returns dict with matched/created/skipped counts.
    """
    # Fetch all contacts from Networking App
    try:
        resp = httpx.get(
            f"{NETWORKING_APP_URL}/api/contacts",
            params={"limit": 500},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch contacts: {resp.status_code}")
        networking_contacts = resp.json()
    except httpx.ConnectError:
        raise RuntimeError("Networking App not reachable at " + NETWORKING_APP_URL)

    if not isinstance(networking_contacts, list):
        networking_contacts = networking_contacts.get("contacts", [])

    conn = get_connection()
    stats = {"matched": 0, "created": 0, "skipped": 0, "total_fetched": len(networking_contacts)}

    try:
        # Load existing unified_contacts
        existing = conn.execute("SELECT * FROM unified_contacts").fetchall()
        existing_by_name = {}
        existing_by_naid = set()
        for r in existing:
            rd = dict(r)
            existing_by_name[rd["canonical_name"].lower().strip()] = rd
            if rd.get("networking_app_contact_id"):
                existing_by_naid.add(rd["networking_app_contact_id"])

        for nc in networking_contacts:
            nc_id = nc.get("id")
            nc_name = (nc.get("name") or "").strip()
            if not nc_name:
                stats["skipped"] += 1
                continue

            # Already linked?
            if nc_id in existing_by_naid:
                # Still update relationships if missing
                _update_relationships(conn, nc, nc_id)
                stats["skipped"] += 1
                continue

            # Build relationship data
            relationships = _build_relationships(nc)
            aliases = _build_aliases(nc, relationships)

            # Match by name
            match_key = nc_name.lower().strip()
            if match_key in existing_by_name:
                # Link existing contact
                uc = existing_by_name[match_key]
                # Merge aliases
                old_aliases = uc.get("aliases") or ""
                merged_aliases = _merge_aliases(old_aliases, aliases)

                conn.execute(
                    """UPDATE unified_contacts
                       SET networking_app_contact_id = ?,
                           email = COALESCE(email, ?),
                           phone_number = COALESCE(phone_number, ?),
                           aliases = ?,
                           relationships = ?
                       WHERE id = ?""",
                    (nc_id, nc.get("email"), nc.get("phone"),
                     merged_aliases, json.dumps(relationships) if relationships else None,
                     uc["id"]),
                )
                stats["matched"] += 1
            else:
                # Create new unified_contact
                new_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO unified_contacts
                       (id, canonical_name, networking_app_contact_id,
                        email, phone_number, aliases, relationships, is_confirmed)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                    (new_id, nc_name, nc_id,
                     nc.get("email"), nc.get("phone"),
                     aliases if aliases else None,
                     json.dumps(relationships) if relationships else None),
                )
                stats["created"] += 1

        conn.commit()
        logger.info(f"Contact sync complete: {stats}")

        # Release any pending routes for entities that now have networking_app_contact_id
        try:
            from sauron.routing.routing_log import release_pending_routes, get_pending_routes_for_entity
            # Find all entities with pending routes
            pending_entities = conn.execute(
                """SELECT DISTINCT rl.entity_id, uc.networking_app_contact_id
                   FROM routing_log rl
                   JOIN unified_contacts uc ON rl.entity_id = uc.id
                   WHERE rl.status = 'pending_entity'
                     AND uc.networking_app_contact_id IS NOT NULL"""
            ).fetchall()
            for pe in pending_entities:
                pe_dict = dict(pe)
                release_pending_routes(
                    pe_dict["entity_id"],
                    pe_dict["networking_app_contact_id"],
                    conn,
                )
            if pending_entities:
                conn.commit()
                logger.info(f"Released pending routes for {len(pending_entities)} entities after sync")
        except Exception:
            logger.exception("Failed to release pending routes after contact sync")

    finally:
        conn.close()

    return stats


def _build_relationships(nc: dict) -> dict:
    """Extract relationship context from a Networking App contact."""
    rels = {}

    partner = (nc.get("partnerName") or "").strip()
    if partner:
        rels["partner_name"] = partner

    partner_id = nc.get("partnerContactId")
    if partner_id:
        rels["partner_contact_id"] = partner_id

    kids = nc.get("kids")
    if kids:
        rels["kids"] = kids

    personal_ring = nc.get("personalRing")
    if personal_ring:
        rels["personal_ring"] = personal_ring

    personal_group = nc.get("personalGroup")
    if personal_group:
        rels["personal_group"] = personal_group

    how_we_met = (nc.get("howWeMet") or "").strip()
    if how_we_met:
        rels["how_we_met"] = how_we_met

    contact_type = nc.get("contactType")
    if contact_type:
        rels["contact_type"] = contact_type

    # Tags may contain relationship info
    tags = nc.get("tags")
    if tags:
        try:
            tag_list = json.loads(tags) if isinstance(tags, str) else tags
            if tag_list:
                rels["tags"] = tag_list
        except (json.JSONDecodeError, TypeError):
            pass

    categories = nc.get("categories")
    if categories:
        try:
            cat_list = json.loads(categories) if isinstance(categories, str) else categories
            if cat_list:
                rels["categories"] = cat_list
        except (json.JSONDecodeError, TypeError):
            pass

    # Rich personal context fields
    notes = (nc.get("notes") or "").strip()
    if notes:
        rels["notes"] = notes

    emotional_context = (nc.get("emotionalContext") or "").strip()
    if emotional_context:
        rels["emotional_context"] = emotional_context

    dietary_notes = (nc.get("dietaryNotes") or "").strip()
    if dietary_notes:
        rels["dietary_notes"] = dietary_notes

    # Location data
    street = (nc.get("streetAddress") or "").strip()
    neighborhood = (nc.get("neighborhood") or "").strip()
    city = (nc.get("city") or "").strip()
    if street or neighborhood or city:
        location = {}
        if street:
            location["street"] = street
        if neighborhood:
            location["neighborhood"] = neighborhood
        if city:
            location["city"] = city
        rels["location"] = location

    return rels


def _build_aliases(nc: dict, relationships: dict) -> str:
    """Build alias string including relational aliases.

    E.g., if contact is Stephen's brother named "Mike Andrews",
    aliases would include "Stephen's brother", "my brother".
    """
    alias_parts = []
    nc_name = (nc.get("name") or "").strip()

    # Check tags for relational terms
    tags = relationships.get("tags", [])
    for tag in tags:
        tag_lower = tag.lower().strip()
        if tag_lower in RELATION_LABELS:
            alias_parts.append(f"Stephen's {tag_lower}")
            alias_parts.append(f"my {tag_lower}")

    # Check personal_group for relational terms
    group = (relationships.get("personal_group") or "").lower().strip()
    if group in RELATION_LABELS:
        alias_parts.append(f"Stephen's {group}")
        alias_parts.append(f"my {group}")

    # Check how_we_met for relational context
    how_met = relationships.get("how_we_met", "").lower()
    for term in RELATION_LABELS:
        if term in how_met:
            alias_parts.append(f"Stephen's {term}")
            alias_parts.append(f"my {term}")

    # If they have a partner listed, that partner's contact could reference
    # this person as "X's wife/husband/partner"
    partner = relationships.get("partner_name", "")
    if partner:
        alias_parts.append(f"{nc_name}'s partner")

    # Scan notes for relational terms (e.g., "Stephen's brother-in-law")
    notes = relationships.get("notes", "").lower()
    if notes:
        for term in RELATION_LABELS:
            if term in notes and f"my {term}" not in alias_parts:
                alias_parts.append(f"Stephen's {term}")
                alias_parts.append(f"my {term}")

    return "; ".join(alias_parts) if alias_parts else ""


def _merge_aliases(old: str, new: str) -> str:
    """Merge old and new alias strings, deduplicating."""
    old_parts = set(a.strip() for a in (old or "").split(";") if a.strip())
    new_parts = set(a.strip() for a in (new or "").split(";") if a.strip())
    merged = old_parts | new_parts
    return "; ".join(sorted(merged)) if merged else ""


def _update_relationships(conn, nc: dict, nc_id: str):
    """Update relationships JSON for an already-linked contact."""
    relationships = _build_relationships(nc)
    if not relationships:
        return
    aliases = _build_aliases(nc, relationships)

    row = conn.execute(
        "SELECT id, aliases FROM unified_contacts WHERE networking_app_contact_id = ?",
        (nc_id,),
    ).fetchone()
    if row:
        merged_aliases = _merge_aliases(dict(row).get("aliases", ""), aliases)
        conn.execute(
            "UPDATE unified_contacts SET relationships = ?, aliases = ? WHERE id = ?",
            (json.dumps(relationships), merged_aliases, dict(row)["id"]),
        )
