"""Entity management API — CRUD for unified_entities.

Provides endpoints for listing, searching, confirming, dismissing, and merging
non-person entities (organizations, legislation, topics).
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entities", tags=["entities"])

# ── Subtype table mapping ────────────────────────────────────────
_SUBTYPE_TABLE = {
    "organization": "entity_organizations",
    "legislation": "entity_legislation",
    "topic": "entity_topics",
}

_SUBTYPE_FIELDS = {
    "entity_organizations": [
        "industry", "org_category", "headquarters",
        "parent_org_entity_id", "networking_app_org_id", "website",
    ],
    "entity_legislation": [
        "bill_number", "congress", "chamber", "committee",
        "status", "policy_area", "sponsor_names",
    ],
    "entity_topics": ["domain", "parent_topic_entity_id"],
}


# ── Models ───────────────────────────────────────────────────────

class EntityUpdate(BaseModel):
    canonical_name: str | None = None
    aliases: str | None = None
    description: str | None = None
    metadata: dict | None = None  # subtype-specific fields


# ── Endpoints ────────────────────────────────────────────────────

@router.get("")
def list_entities(
    entity_type: str | None = None,
    is_confirmed: int | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List all entities, filterable by type and confirmation status."""
    conn = get_connection()
    try:
        clauses = []
        params = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if is_confirmed is not None:
            clauses.append("is_confirmed = ?")
            params.append(is_confirmed)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""SELECT id, entity_type, canonical_name, aliases, description,
                       is_confirmed, observation_count, first_observed_at,
                       last_observed_at, created_at
                FROM unified_entities
                {where}
                ORDER BY observation_count DESC, canonical_name
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/search")
def search_entities(q: str = Query(..., min_length=1), limit: int = 20):
    """Typeahead search across entity canonical_name + aliases."""
    conn = get_connection()
    try:
        search_term = f"%{q}%"
        rows = conn.execute(
            """SELECT id, entity_type, canonical_name, aliases, description,
                      is_confirmed, observation_count
               FROM unified_entities
               WHERE canonical_name LIKE ? OR aliases LIKE ?
               ORDER BY
                  is_confirmed DESC,
                  CASE WHEN LOWER(canonical_name) = LOWER(?) THEN 0
                       WHEN canonical_name LIKE ? THEN 1
                       ELSE 2 END,
                  observation_count DESC
               LIMIT ?""",
            (search_term, search_term, q.strip(), f"{q}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/provisional")
def list_provisional_entities(limit: int = 50):
    """List unconfirmed entities for review."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT ue.id, ue.entity_type, ue.canonical_name, ue.aliases,
                      ue.description, ue.observation_count, ue.first_observed_at,
                      ue.last_observed_at, ue.source_conversation_id
               FROM unified_entities ue
               WHERE ue.is_confirmed = 0
               ORDER BY ue.observation_count DESC, ue.last_observed_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{entity_id}")
def get_entity(entity_id: str):
    """Get entity detail with subtype metadata."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT id, entity_type, canonical_name, aliases, description,
                      is_confirmed, observation_count, first_observed_at,
                      last_observed_at, source_conversation_id, created_at
               FROM unified_entities WHERE id = ?""",
            (entity_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entity not found")

        result = dict(row)

        # Load subtype metadata
        subtype_table = _SUBTYPE_TABLE.get(result["entity_type"])
        if subtype_table:
            sub_row = conn.execute(
                f"SELECT * FROM {subtype_table} WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            if sub_row:
                sub_dict = dict(sub_row)
                sub_dict.pop("entity_id", None)
                result["metadata"] = sub_dict

        # Load claim count
        claim_count = conn.execute(
            """SELECT COUNT(*) as n FROM claim_entities
               WHERE entity_id = ? AND entity_table = 'unified_entities'""",
            (entity_id,),
        ).fetchone()["n"]
        result["claim_count"] = claim_count

        return result
    finally:
        conn.close()


@router.patch("/{entity_id}")
def update_entity(entity_id: str, update: EntityUpdate):
    """Update entity canonical_name, aliases, description, or subtype metadata."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT entity_type FROM unified_entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entity not found")

        entity_type = row["entity_type"]

        # Update core fields
        updates = []
        params = []
        if update.canonical_name is not None:
            updates.append("canonical_name = ?")
            params.append(update.canonical_name.strip())
        if update.aliases is not None:
            updates.append("aliases = ?")
            params.append(update.aliases.strip())
        if update.description is not None:
            updates.append("description = ?")
            params.append(update.description.strip())

        if updates:
            conn.execute(
                f"UPDATE unified_entities SET {', '.join(updates)} WHERE id = ?",
                params + [entity_id],
            )

        # Update subtype metadata
        if update.metadata:
            subtype_table = _SUBTYPE_TABLE.get(entity_type)
            if subtype_table:
                allowed = _SUBTYPE_FIELDS.get(subtype_table, [])
                sub_updates = []
                sub_params = []
                for field, value in update.metadata.items():
                    if field in allowed:
                        sub_updates.append(f"{field} = ?")
                        sub_params.append(value)
                if sub_updates:
                    # Ensure subtype row exists
                    conn.execute(
                        f"INSERT OR IGNORE INTO {subtype_table} (entity_id) VALUES (?)",
                        (entity_id,),
                    )
                    conn.execute(
                        f"UPDATE {subtype_table} SET {', '.join(sub_updates)} WHERE entity_id = ?",
                        sub_params + [entity_id],
                    )

        conn.commit()
        return {"status": "ok", "entity_id": entity_id}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/{entity_id}/confirm")
def confirm_entity(entity_id: str):
    """Confirm a provisional entity. Handles virtual ge: IDs from graph_edges."""
    conn = get_connection()
    try:
        # Handle virtual graph_edge entities (id starts with "ge:")
        if entity_id.startswith("ge:"):
            name = entity_id[3:]
            # Check if already exists by name
            existing = conn.execute(
                "SELECT id FROM unified_entities WHERE LOWER(canonical_name) = LOWER(?)",
                (name,),
            ).fetchone()
            if existing:
                entity_id = existing["id"]
            else:
                # Create new entity and confirm it
                entity_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO unified_entities
                       (id, entity_type, canonical_name, is_confirmed,
                        observation_count, created_at)
                       VALUES (?, 'organization', ?, 1, 1, datetime('now'))""",
                    (entity_id, name),
                )
                conn.commit()
                logger.info(f"Created + confirmed entity '{name}' from graph_edge")
                return {"status": "confirmed", "entity_id": entity_id, "created": True}

        row = conn.execute(
            "SELECT canonical_name, is_confirmed FROM unified_entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entity not found")

        if row["is_confirmed"]:
            return {"status": "already_confirmed"}

        conn.execute(
            "UPDATE unified_entities SET is_confirmed = 1 WHERE id = ?",
            (entity_id,),
        )

        # Run cascade
        try:
            from sauron.extraction.cascade import cascade_object_confirmation
            stats = cascade_object_confirmation(
                conn, entity_id, row["canonical_name"],
                [row["canonical_name"]],
            )
            logger.info(f"Entity confirm cascade for '{row['canonical_name']}': {stats}")
        except Exception:
            logger.exception("Entity confirm cascade failed (non-fatal)")

        conn.commit()
        return {"status": "confirmed", "entity_id": entity_id}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/{entity_id}/dismiss")
def dismiss_entity(entity_id: str):
    """Dismiss a provisional entity — removes claim links and deletes entity."""
    # Virtual graph_edge entities — no DB row to delete, just ack
    if entity_id.startswith("ge:"):
        return {"status": "dismissed", "entity_id": entity_id}

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT entity_type FROM unified_entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entity not found")

        # Remove claim_entities links
        conn.execute(
            "DELETE FROM claim_entities WHERE entity_id = ? AND entity_table = 'unified_entities'",
            (entity_id,),
        )

        # Clear subject_entity_id on event_claims pointing to this entity
        conn.execute(
            "UPDATE event_claims SET subject_entity_id = NULL WHERE subject_entity_id = ?",
            (entity_id,),
        )

        # Remove graph_edges entity references
        conn.execute(
            "UPDATE graph_edges SET from_entity_id = NULL, from_entity_table = NULL WHERE from_entity_id = ?",
            (entity_id,),
        )
        conn.execute(
            "UPDATE graph_edges SET to_entity_id = NULL, to_entity_table = NULL WHERE to_entity_id = ?",
            (entity_id,),
        )

        # Remove beliefs
        conn.execute("DELETE FROM beliefs WHERE entity_id = ?", (entity_id,))

        # Delete subtype row
        subtype_table = _SUBTYPE_TABLE.get(row["entity_type"])
        if subtype_table:
            conn.execute(f"DELETE FROM {subtype_table} WHERE entity_id = ?", (entity_id,))

        # Delete entity
        conn.execute("DELETE FROM unified_entities WHERE id = ?", (entity_id,))

        conn.commit()
        return {"status": "dismissed", "entity_id": entity_id}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/{entity_id}/merge/{other_id}")
def merge_entities(entity_id: str, other_id: str):
    """Merge other_id into entity_id (keeper). Mirrors resolve_duplicate_contacts."""
    conn = get_connection()
    try:
        keeper = conn.execute(
            "SELECT * FROM unified_entities WHERE id = ?", (entity_id,)
        ).fetchone()
        dupe = conn.execute(
            "SELECT * FROM unified_entities WHERE id = ?", (other_id,)
        ).fetchone()

        if not keeper or not dupe:
            raise HTTPException(status_code=404, detail="Entity not found")
        if dict(keeper)["entity_type"] != dict(dupe)["entity_type"]:
            raise HTTPException(status_code=400, detail="Cannot merge entities of different types")

        keeper_d = dict(keeper)
        dupe_d = dict(dupe)

        # Merge aliases
        keeper_aliases = set(a.strip() for a in (keeper_d["aliases"] or "").split(";") if a.strip())
        dupe_aliases = set(a.strip() for a in (dupe_d["aliases"] or "").split(";") if a.strip())
        dupe_aliases.add(dupe_d["canonical_name"])  # add dupe's name as alias
        merged_aliases = "; ".join(sorted(keeper_aliases | dupe_aliases))

        # Merge description (null-only)
        desc = keeper_d["description"] or dupe_d["description"]

        # Update keeper
        conn.execute(
            """UPDATE unified_entities
               SET aliases = ?, description = ?,
                   observation_count = observation_count + ?,
                   is_confirmed = MAX(is_confirmed, ?)
               WHERE id = ?""",
            (merged_aliases, desc, dupe_d["observation_count"],
             dupe_d["is_confirmed"], entity_id),
        )

        # Merge subtype metadata (null-only patching)
        subtype_table = _SUBTYPE_TABLE.get(keeper_d["entity_type"])
        if subtype_table:
            fields = _SUBTYPE_FIELDS.get(subtype_table, [])
            for field in fields:
                conn.execute(
                    f"""UPDATE {subtype_table}
                        SET {field} = COALESCE({field}, (
                            SELECT {field} FROM {subtype_table} WHERE entity_id = ?
                        ))
                        WHERE entity_id = ?""",
                    (other_id, entity_id),
                )

        # Re-point claim_entities
        conn.execute(
            """UPDATE claim_entities SET entity_id = ?, entity_name = ?
               WHERE entity_id = ? AND entity_table = 'unified_entities'""",
            (entity_id, keeper_d["canonical_name"], other_id),
        )

        # Re-point graph_edges
        conn.execute(
            "UPDATE graph_edges SET from_entity_id = ? WHERE from_entity_id = ? AND from_entity_table = 'unified_entities'",
            (entity_id, other_id),
        )
        conn.execute(
            "UPDATE graph_edges SET to_entity_id = ? WHERE to_entity_id = ? AND to_entity_table = 'unified_entities'",
            (entity_id, other_id),
        )

        # Re-point beliefs
        conn.execute(
            "UPDATE beliefs SET entity_id = ? WHERE entity_id = ?",
            (entity_id, other_id),
        )

        # Re-point event_claims
        conn.execute(
            "UPDATE event_claims SET subject_entity_id = ? WHERE subject_entity_id = ?",
            (entity_id, other_id),
        )

        # Delete dupe subtype row
        if subtype_table:
            conn.execute(f"DELETE FROM {subtype_table} WHERE entity_id = ?", (other_id,))

        # Delete dupe
        conn.execute("DELETE FROM unified_entities WHERE id = ?", (other_id,))

        conn.commit()
        logger.info(f"Merged entity '{dupe_d['canonical_name']}' into '{keeper_d['canonical_name']}'")
        return {
            "status": "merged",
            "keeper_id": entity_id,
            "merged_id": other_id,
            "merged_name": dupe_d["canonical_name"],
        }
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
