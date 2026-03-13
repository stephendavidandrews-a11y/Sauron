"""Entity resolution helpers for routing lanes.

Extracted from sauron/routing/networking.py (stability refactor).
"""

import json as _json
import logging
import uuid

logger = logging.getLogger(__name__)


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

    IMPORTANT (Step F): Does NOT fall back to the conversation's primary
    contact. If the entity name cannot be resolved, returns None.
    The fallback_contact_id is ONLY used when entity_name is empty/None
    (i.e., no entity was specified, so the caller explicitly wants the
    primary contact). This prevents misattributing data about "person X"
    to the primary contact just because X couldn't be resolved.
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
        # Step F: Return None on miss — do NOT fall back to primary.
        # Callers must handle None (skip the object) rather than
        # silently misattribute to the conversation's primary contact.
        return None
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
