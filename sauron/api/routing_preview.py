"""Routing preview endpoint extracted from conversations.py.

Contains: get_routing_preview (GET /{conversation_id}/routing-preview)
and its helper _get_object_summary.
"""

import json
import logging

from fastapi import APIRouter

from sauron.db.connection import get_connection
from sauron.api.people_endpoints import _OBJ_TYPE_SINGULAR

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_object_summary(obj_type_plural: str, item: dict) -> str:
    """Extract a human-readable summary from a synthesis object."""
    if obj_type_plural == "standing_offers":
        return (item.get("description") or item.get("offer") or "")[:120]
    elif obj_type_plural == "scheduling_leads":
        return (item.get("description") or item.get("suggested_meeting") or "")[:120]
    elif obj_type_plural == "graph_edges":
        f = item.get("from_entity", "")
        t = item.get("to_entity", "")
        r = item.get("edge_type") or item.get("relationship", "")
        return f"{f} -> {r} -> {t}"
    elif obj_type_plural == "new_contacts_mentioned":
        return (item.get("name") or "") + ": " + (item.get("context") or "")[:80]
    elif obj_type_plural == "contact_commitments":
        return (item.get("description") or "")[:120]
    elif obj_type_plural == "my_commitments":
        return (item.get("description") or "")[:120]
    elif obj_type_plural == "follow_ups":
        return (item.get("description") or "")[:120]
    elif obj_type_plural == "policy_positions":
        topic = item.get('topic', '')
        person = item.get('person', '') or item.get('entity', '')
        return f"{person}: {item.get('position', '')} {topic}"[:120]
    return str(item)[:120]


@router.get("/{conversation_id}/routing-preview")
def get_routing_preview(conversation_id: str):
    """Preview routing readiness for synthesis objects in a conversation.

    Groups by synthesis object type (standing_offers, scheduling_leads,
    graph_edges, etc). Each object shows entity resolution status and
    which person is blocking it.
    """
    conn = get_connection()
    try:
        # Get the pass-3 synthesis extraction
        extraction = conn.execute("""
            SELECT extraction_json FROM extractions
            WHERE conversation_id = ? AND pass_number = 3
            ORDER BY rowid DESC LIMIT 1
        """, (conversation_id,)).fetchone()

        if not extraction:
            return {"ready_count": 0, "blocked_count": 0, "objects": {}}

        synthesis = json.loads(extraction["extraction_json"])

        # Get all synthesis_entity_links for this conversation
        links = conn.execute("""
            SELECT sel.object_type, sel.object_index, sel.field_name,
                   sel.original_name, sel.resolved_entity_id, sel.link_source,
                   sel.confidence,
                   uc.canonical_name, uc.is_confirmed
            FROM synthesis_entity_links sel
            LEFT JOIN unified_contacts uc ON uc.id = sel.resolved_entity_id
            WHERE sel.conversation_id = ?
        """, (conversation_id,)).fetchall()

        # Group links by (object_type, object_index)
        link_map = {}
        for link in links:
            key = (link["object_type"], link["object_index"])
            if key not in link_map:
                link_map[key] = []
            link_map[key].append(dict(link))

        # Object types to include in routing preview (person-bearing objects)
        ROUTABLE_TYPES = [
            "standing_offers", "scheduling_leads", "graph_edges",
            "contact_commitments", "policy_positions",
        ]

        objects = {}
        ready_count = 0
        blocked_count = 0
        skipped_count = 0

        for obj_type_plural in ROUTABLE_TYPES:
            items = synthesis.get(obj_type_plural, [])
            if not items:
                continue

            obj_type_singular = _OBJ_TYPE_SINGULAR.get(obj_type_plural, obj_type_plural.rstrip("s"))
            obj_list = []

            for idx, item in enumerate(items):
                people_refs = link_map.get((obj_type_singular, idx), [])

                blockers = []
                people = []
                for ref in people_refs:
                    if ref["link_source"] == "skipped":
                        people.append({
                            "name": ref["original_name"],
                            "entity_id": ref["resolved_entity_id"],
                            "canonical_name": ref["canonical_name"],
                            "resolved": True,
                            "skipped": True,
                        })
                    elif ref["resolved_entity_id"] and ref["is_confirmed"]:
                        people.append({
                            "name": ref["original_name"],
                            "entity_id": ref["resolved_entity_id"],
                            "canonical_name": ref["canonical_name"],
                            "resolved": True,
                            "skipped": False,
                        })
                    else:
                        reason = "unresolved" if not ref["resolved_entity_id"] else "provisional"
                        blockers.append(f"{ref['original_name']} is {reason}")
                        people.append({
                            "name": ref["original_name"],
                            "entity_id": ref["resolved_entity_id"],
                            "canonical_name": ref.get("canonical_name"),
                            "resolved": False,
                            "skipped": False,
                        })

                has_skipped = any(p.get("skipped") for p in people)
                if blockers:
                    status = "blocked"
                    blocked_count += 1
                elif has_skipped:
                    status = "skipped"
                    skipped_count += 1
                else:
                    status = "ready"
                    ready_count += 1

                summary = _get_object_summary(obj_type_plural, item)

                entry = {
                    "index": idx,
                    "summary": summary,
                    "status": status,
                    "people": people,
                }
                if blockers:
                    entry["blocker"] = "; ".join(blockers)

                obj_list.append(entry)

            if obj_list:
                objects[obj_type_plural] = obj_list

        return {
            "ready_count": ready_count,
            "blocked_count": blocked_count,
            "skipped_count": skipped_count,
            "objects": objects,
        }
    finally:
        conn.close()
