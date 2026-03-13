"""Knowledge graph and contacts API endpoints.

V8: Added provisional contact triage endpoints (list, link, confirm, dismiss).
"""

import json
import logging
import uuid


def _is_transcription_error(old_name: str, new_name: str) -> bool:
    """Check if a name change represents a genuine transcription error.

    Returns True only when old and new names share NO common words.
    Examples:
      "Wieden" -> "Wyden"  => True  (no common words, Whisper misheard)
      "Lee" -> "Mike Lee"  => False (Lee is in both, just incomplete)
      "Daniel" -> "Daniel Park" => False (Daniel is in both)
    """
    old_words = {w.lower() for w in old_name.strip().split()}
    new_words = {w.lower() for w in new_name.strip().split()}
    return len(old_words & new_words) == 0


from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from sauron.db.connection import get_connection
from sauron.api.relational_terms import RELATIONAL_TERMS, PLURAL_TERMS, ALL_TERMS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])


# ── Pydantic models ────────────────────────────────────────────

class ProvisionalLinkRequest(BaseModel):
    """Link a provisional contact to an existing confirmed contact."""
    target_contact_id: str
    user_feedback: Optional[str] = None


class ProvisionalConfirmRequest(BaseModel):
    """Confirm a provisional contact as a real new contact."""
    canonical_name: Optional[str] = None  # Override name if needed
    email: Optional[str] = None
    phone: Optional[str] = None
    aliases: Optional[str] = None  # Semicolon-separated
    push_to_networking_app: bool = False
    user_feedback: Optional[str] = None


class CreateContactRequest(BaseModel):
    """Create a new confirmed contact directly."""
    canonical_name: str
    original_name: Optional[str] = None  # The extracted name being resolved
    organization: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    aliases: Optional[str] = None  # Semicolon-separated
    notes: Optional[str] = None
    push_to_networking_app: bool = True
    source_conversation_id: Optional[str] = None


# ── Existing endpoints ──────────────────────────────────────────

def _replay_pending_object_routes(entity_id: str, networking_app_contact_id: str, conn):
    """Replay pending object routes for a confirmed entity.

    Unlike release_pending_routes (which replays full conversation routing from routing_log),
    this replays individual object-level holds from pending_object_routes.
    """
    import json as _json
    from sauron.routing.lanes.core import _api_call
    from sauron.config import NETWORKING_APP_URL

    pending = conn.execute(
        """SELECT id, conversation_id, route_type, payload
           FROM pending_object_routes
           WHERE blocked_on_entity = ? AND status = 'pending'""",
        (entity_id,),
    ).fetchall()

    if not pending:
        return 0

    released = 0
    for route in pending:
        payload = _json.loads(route["payload"])

        if route["route_type"] == "graph_edge":
            # Fill in the resolved contact ID for the blocked endpoint
            if not payload.get("from_cid"):
                payload["from_cid"] = networking_app_contact_id
            if not payload.get("to_cid"):
                payload["to_cid"] = networking_app_contact_id

            # Skip self-referential
            if payload["from_cid"] == payload["to_cid"]:
                conn.execute(
                    "UPDATE pending_object_routes SET status = 'released', released_at = datetime('now') WHERE id = ?",
                    (route["id"],),
                )
                released += 1
                continue

            edge_payload = {
                "contactAId": payload["from_cid"],
                "contactBId": payload["to_cid"],
                "relationshipType": payload.get("edge_type", "knows"),
                "strength": int(payload.get("strength", 0.5) * 5) + 1,
                "source": "sauron",
                "observationSource": f"Conversation {route['conversation_id'][:8]}",
                "sourceSystem": payload.get("sourceSystem", "sauron"),
                "sourceId": payload.get("sourceId", route["conversation_id"]),
            }
            ok, err = _api_call(
                "POST", f"{NETWORKING_APP_URL}/api/contact-relationships", edge_payload
            )
            if ok:
                conn.execute(
                    "UPDATE pending_object_routes SET status = 'released', released_at = datetime('now') WHERE id = ?",
                    (route["id"],),
                )
                released += 1
            else:
                logger.warning(f"Failed to replay pending route {route['id'][:8]}: {err}")

        else:
            # Future route types (provenance, etc.) can be handled here
            logger.debug(f"Unsupported pending route type: {route['route_type']}")

    if released:
        conn.commit()
        logger.info(f"Replayed {released}/{len(pending)} pending object routes for entity {entity_id[:8]}")

    return released


@router.get("")
def list_contacts(limit: int = 500):
    """List all unified contacts with conversation counts."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT uc.*,
                  (SELECT COUNT(DISTINCT t.conversation_id)
                   FROM transcripts t WHERE t.speaker_id = uc.id) as conversation_count,
                  CASE WHEN uc.voice_profile_id IS NOT NULL THEN 1 ELSE 0 END as voice_enrolled
               FROM unified_contacts uc
               ORDER BY uc.canonical_name
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return {"contacts": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/search")
def search_contacts(q: str = Query(..., min_length=1), limit: int = 20):
    """Search contacts by name or alias for entity linking.

    Returns only canonical networking-app contacts (networking_app_contact_id IS NOT NULL)
    as the authoritative source for review linking flows. Deduplicates by
    networking_app_contact_id to handle legacy duplicate rows in unified_contacts.
    """
    conn = get_connection()
    try:
        search_term = f"%{q}%"
        rows = conn.execute(
            """SELECT id, canonical_name, email, phone_number, aliases, relationships,
                  networking_app_contact_id, voice_profile_id, is_confirmed
               FROM unified_contacts
               WHERE networking_app_contact_id IS NOT NULL
                 AND is_confirmed = 1
                 AND (canonical_name LIKE ?
                      OR aliases LIKE ?
                      OR email LIKE ?)
               ORDER BY
                  CASE WHEN canonical_name LIKE ? THEN 0 ELSE 1 END,
                  source_conversation_id IS NOT NULL,
                  canonical_name
               LIMIT ?""",
            (search_term, search_term, search_term, search_term, limit),
        ).fetchall()

        # Deduplicate by networking_app_contact_id (keep first seen = preferred row)
        seen_naid = set()
        deduped = []
        for r in rows:
            d = dict(r)
            naid = d.get("networking_app_contact_id")
            if naid in seen_naid:
                continue
            seen_naid.add(naid)
            deduped.append(d)

        return deduped
    finally:
        conn.close()


@router.post("/sync-contacts")
def trigger_contact_sync():
    """Sync contacts from Networking App into unified_contacts."""
    from sauron.contacts.sync import sync_contacts_from_networking_app
    try:
        stats = sync_contacts_from_networking_app()
        return {"status": "ok", **stats}
    except RuntimeError as e:
        return {"status": "error", "detail": str(e)}


@router.get("/query")
def query_graph(
    entity: str | None = None,
    entity_type: str | None = None,
    edge_type: str | None = None,
    limit: int = 100,
):
    """Query the knowledge graph edges."""
    conn = get_connection()
    try:
        query = "SELECT * FROM graph_edges WHERE 1=1"
        params = []

        if entity:
            query += " AND (from_entity = ? OR to_entity = ?)"
            params.extend([entity, entity])
        if entity_type:
            query += " AND (from_type = ? OR to_type = ?)"
            params.extend([entity_type, entity_type])
        if edge_type:
            query += " AND edge_type = ?"
            params.append(edge_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/contacts/{contact_id}/connections")
def get_contact_connections(contact_id: str):
    """Get all graph edges involving a specific contact."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM graph_edges
               WHERE (from_entity = ? AND from_type = 'person')
                  OR (to_entity = ? AND to_type = 'person')
               ORDER BY strength DESC""",
            (contact_id, contact_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()




@router.get("/unresolved-relational")
def list_unresolved_relational_claims(conversation_id: str | None = None, limit: int = 50):
    """List claims with relational references that haven't been resolved.

    These are claims where the text mentions a relational term (son, wife, brother etc.)
    but the referenced person hasn't been linked to a contact yet.
    Returns claims that need manual entity linking for the relational reference.
    """
    RELATIONAL_TERMS_SQL = [
        "'s son", "'s sons", "'s daughter", "'s daughters",
        "'s wife", "'s husband", "'s brother", "'s brothers",
        "'s sister", "'s sisters", "'s mother", "'s father",
        "'s mom", "'s dad", "'s boss", "'s colleague",
        "'s partner", "'s friend", "'s uncle", "'s aunt", "'s cousin",
        "'s baby", "'s babies", "'s child", "'s children", "'s kid", "'s kids",
        "my son", "my sons", "my daughter", "my wife", "my husband",
        "my brother", "my brothers", "my sister", "my sisters",
        "my mother", "my father", "my mom", "my dad",
        "my boss", "my colleague", "my partner", "my friend",
        "my baby", "my babies", "my child", "my children", "my kid", "my kids",
        "his son", "his sons", "his daughter", "his wife", "his brother",
        "his sister", "his mother", "his father", "his mom", "his dad",
        "his baby", "his babies", "his child", "his children", "his kid", "his kids",
        "her son", "her sons", "her daughter", "her husband", "her brother",
        "her sister", "her mother", "her father", "her mom", "her dad",
        "her baby", "her babies", "her child", "her children", "her kid", "her kids",
    ]

    conn = get_connection()
    try:
        # Build OR conditions for LIKE matching
        conditions = " OR ".join(
            f"LOWER(ec.claim_text) LIKE ?"
            for _ in RELATIONAL_TERMS_SQL
        )
        params = [f"%{t}%" for t in RELATIONAL_TERMS_SQL]

        query = f"""
            SELECT ec.id, ec.claim_text, ec.claim_type, ec.subject_name,
                   ec.subject_entity_id, ec.conversation_id, ec.episode_id,
                   ec.target_entity, ec.speaker_id
            FROM event_claims ec
            WHERE ({conditions})
        """

        if conversation_id:
            query += " AND ec.conversation_id = ?"
            params.append(conversation_id)

        query += " ORDER BY ec.created_at LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        # Enrich: for each claim, identify the anchor person and the relational term
        import re as _re
        results = []
        for r in rows:
            d = dict(r)

            # Detect relational reference
            text = d["claim_text"] or ""
            text_lower = text.lower()

            detected_term = None
            anchor_ref = None

            # Check possessive patterns: "Name's [relation]"
            poss_pattern = _re.compile(r"(\b[A-Z]\w+(?:\s+[A-Z]\w+)?)'s\s+(\w+)", _re.IGNORECASE)
            for m in poss_pattern.finditer(text):
                term = m.group(2).lower()
                rel_terms = {"son", "sons", "daughter", "daughters",
                            "wife", "husband", "brother", "brothers", "sister", "sisters",
                            "mother", "father", "mom", "dad", "boss", "colleague",
                            "partner", "friend", "uncle", "aunt", "cousin",
                            "baby", "babies", "child", "children", "kid", "kids"}
                if term in rel_terms:
                    anchor_ref = m.group(1)
                    detected_term = term
                    break

            # Check pronoun patterns: "my/his/her [relation]"
            if not detected_term:
                pron_pattern = _re.compile(r"\b(my|his|her|their)\s+(\w+)\b", _re.IGNORECASE)
                for m in pron_pattern.finditer(text):
                    term = m.group(2).lower()
                    if term in {"son", "sons", "daughter", "daughters",
                               "wife", "husband", "brother", "brothers", "sister", "sisters",
                               "mother", "father", "mom", "dad", "boss", "colleague",
                               "partner", "friend", "baby", "babies", "child", "children",
                               "kid", "kids"}:
                        anchor_ref = m.group(1)
                        detected_term = term
                        break

            # Try to resolve anchor to a contact
            anchor_contact = None
            if anchor_ref and anchor_ref.lower() not in ("my", "his", "her", "their"):
                anchor_contact_row = conn.execute(
                    """SELECT id, canonical_name FROM unified_contacts
                       WHERE LOWER(canonical_name) LIKE ?
                       LIMIT 1""",
                    (f"%{anchor_ref.lower()}%",),
                ).fetchone()
                if anchor_contact_row:
                    anchor_contact = dict(anchor_contact_row)

            is_plural = detected_term in PLURAL_TERMS if detected_term else False
            d["relational_term"] = detected_term
            d["relational_term_raw"] = detected_term
            d["is_plural"] = is_plural
            d["anchor_reference"] = anchor_ref
            d["anchor_contact"] = anchor_contact
            d["needs_linking"] = d["subject_entity_id"] is None or detected_term is not None
            results.append(d)

        return {
            "relational_claims": results,
            "total": len(results),
        }
    finally:
        conn.close()


# ── Provisional contact triage endpoints ────────────────────────

@router.get("/provisional")
def list_provisional_contacts(
    limit: int = 50,
    conversation_id: str | None = None,
):
    """List provisional (unconfirmed) contacts with their linked claims.

    Returns contacts where is_confirmed = 0 and source_conversation_id is set,
    along with the claims that reference them.

    Args:
        limit: Max results.
        conversation_id: Optional filter — only show provisional contacts
                        from this specific conversation.
    """
    conn = get_connection()
    try:
        # Get provisional contacts
        query = """SELECT uc.id, uc.canonical_name, uc.aliases, uc.email,
                      uc.source_conversation_id, uc.created_at,
                      c.source as conversation_source,
                      c.created_at as conversation_date
               FROM unified_contacts uc
               LEFT JOIN conversations c ON c.id = uc.source_conversation_id
               WHERE uc.is_confirmed = 0
                 AND uc.source_conversation_id IS NOT NULL"""
        params = []

        if conversation_id:
            query += " AND uc.source_conversation_id = ?"
            params.append(conversation_id)

        query += " ORDER BY uc.created_at DESC LIMIT ?"
        params.append(limit)

        provisionals = conn.execute(query, params).fetchall()

        results = []
        for p in provisionals:
            pd = dict(p)
            contact_id = pd["id"]

            # Get claims linked to this provisional contact
            claims = conn.execute(
                """SELECT ec.id, ec.claim_text, ec.claim_type, ec.subject_name,
                          ec.confidence, ec.conversation_id, ec.episode_id
                   FROM event_claims ec
                   LEFT JOIN claim_entities ce ON ce.claim_id = ec.id AND ce.entity_id = ?
                   WHERE ec.subject_entity_id = ?
                      OR ce.entity_id = ?
                   ORDER BY ec.created_at
                   LIMIT 10""",
                (contact_id, contact_id, contact_id),
            ).fetchall()

            pd["claims"] = [dict(c) for c in claims]
            pd["claim_count"] = len(pd["claims"])
            results.append(pd)

        return {
            "provisional_contacts": results,
            "total": len(results),
        }
    finally:
        conn.close()


@router.post("/provisional/{contact_id}/link")
def link_provisional_to_existing(contact_id: str, request: ProvisionalLinkRequest):
    """Merge a provisional contact into an existing confirmed contact.

    Merge behavior per spec:
    - Keep the canonical (target) contact ID
    - Append alias strings from provisional record
    - Preserve source_conversation_id as provenance on canonical contact
    - Transfer all claim_entities links from provisional to canonical
    - Update event_claims.subject_entity_id references
    - Log a correction_event with error_type: "provisional_contact_merged"
    - Do NOT just delete — preserve provenance trail
    """
    conn = get_connection()
    try:
        # Verify provisional contact exists and is unconfirmed
        provisional = conn.execute(
            "SELECT * FROM unified_contacts WHERE id = ? AND is_confirmed = 0",
            (contact_id,),
        ).fetchone()
        if not provisional:
            raise HTTPException(404, "Provisional contact not found or already confirmed")

        prov = dict(provisional)

        # Verify target contact exists
        target = conn.execute(
            "SELECT * FROM unified_contacts WHERE id = ?",
            (request.target_contact_id,),
        ).fetchone()
        if not target:
            raise HTTPException(404, "Target contact not found")

        target_dict = dict(target)

        # 1. Append aliases from provisional to target
        existing_aliases = target_dict.get("aliases") or ""
        prov_name = prov["canonical_name"]
        if prov_name:
            # Add the provisional name as an alias if not already present
            alias_list = [a.strip() for a in existing_aliases.split(";") if a.strip()]
            if prov_name.lower() not in [a.lower() for a in alias_list]:
                alias_list.append(prov_name)
            # Also add provisional aliases
            prov_aliases = prov.get("aliases") or ""
            for pa in prov_aliases.split(";"):
                pa = pa.strip()
                if pa and pa.lower() not in [a.lower() for a in alias_list]:
                    alias_list.append(pa)
            new_aliases = "; ".join(alias_list)
            conn.execute(
                "UPDATE unified_contacts SET aliases = ? WHERE id = ?",
                (new_aliases, request.target_contact_id),
            )

        # 2. Preserve source_conversation_id as provenance
        # If target doesn't have one, set it; otherwise leave existing
        if not target_dict.get("source_conversation_id") and prov.get("source_conversation_id"):
            conn.execute(
                "UPDATE unified_contacts SET source_conversation_id = ? WHERE id = ?",
                (prov["source_conversation_id"], request.target_contact_id),
            )

        # 3. Transfer claim_entities links from provisional to target
        # Update entity_id and entity_name
        conn.execute(
            """UPDATE claim_entities
               SET entity_id = ?, entity_name = ?
               WHERE entity_id = ?""",
            (request.target_contact_id, target_dict["canonical_name"], contact_id),
        )

        # Handle potential unique constraint violations (same claim+entity+role already exists)
        # Delete any orphaned duplicates
        conn.execute(
            """DELETE FROM claim_entities WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM claim_entities
                GROUP BY claim_id, entity_id, role
            )"""
        )

        # 4. Update event_claims.subject_entity_id
        conn.execute(
            """UPDATE event_claims
               SET subject_entity_id = ?, subject_name = ?
               WHERE subject_entity_id = ?""",
            (request.target_contact_id, target_dict["canonical_name"], contact_id),
        )

        # 5. Log correction event
        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO correction_events
               (id, conversation_id, error_type, old_value, new_value,
                user_feedback, correction_source)
               VALUES (?, ?, 'provisional_contact_merged', ?, ?, ?, 'manual_ui')""",
            (event_id, prov.get("source_conversation_id"),
             f"{prov['canonical_name']} (provisional:{contact_id[:8]})",
             f"{target_dict['canonical_name']} (confirmed:{request.target_contact_id[:8]})",
             request.user_feedback),
        )

        # 5a-extra. Learn alias + log name_transcription if names differ
        if prov["canonical_name"].strip().lower() != target_dict["canonical_name"].strip().lower():
            try:
                from sauron.extraction.alias_learner import learn_alias
                learn_alias(conn, request.target_contact_id, prov["canonical_name"].strip(), target_dict["canonical_name"])
                logger.info("Learned alias (link): '%s' -> '%s'", prov["canonical_name"], target_dict["canonical_name"])
            except Exception:
                logger.exception("Alias learning in link_provisional failed (non-fatal)")
            if _is_transcription_error(prov["canonical_name"].strip(), target_dict["canonical_name"]):
                try:
                    conn.execute(
                        """INSERT INTO correction_events
                           (id, conversation_id, error_type, old_value, new_value, correction_source)
                           VALUES (?, ?, 'name_transcription', ?, ?, 'link_provisional')""",
                        (str(uuid.uuid4()), prov.get("source_conversation_id") or "",
                         prov["canonical_name"].strip(), target_dict["canonical_name"]),
                    )
                except Exception:
                    logger.exception("Correction event logging in link_provisional failed (non-fatal)")

        # 5b. Run entity confirmation cascade (text rewriting, episode titles, synthesis links, etc.)
        try:
            from sauron.extraction.cascade import cascade_entity_confirmation
            _cascade_names = [prov["canonical_name"]]
            _prov_aliases = prov.get("aliases") or ""
            for _pa in _prov_aliases.split(";"):
                _pa = _pa.strip()
                if _pa:
                    _cascade_names.append(_pa)
            _cascade_stats = cascade_entity_confirmation(
                conn, request.target_contact_id, target_dict["canonical_name"],
                _cascade_names,
                conversation_id=None,
                source="link_provisional",
            )
            logger.info(f"Link provisional cascade: {_cascade_stats}")
        except Exception:
            logger.exception("Link provisional cascade failed (non-fatal)")

        # 6. Delete the provisional contact record (links already transferred)
        conn.execute("DELETE FROM unified_contacts WHERE id = ?", (contact_id,))

        # 7. Mark affected beliefs as under_review
        conn.execute(
            """UPDATE beliefs SET status = 'under_review'
               WHERE id IN (
                   SELECT DISTINCT be.belief_id FROM belief_evidence be
                   JOIN event_claims ec ON ec.id = be.claim_id
                   WHERE ec.subject_entity_id = ?
               )""",
            (request.target_contact_id,),
        )

        # 8. Release pending routes for the merged provisional entity
        # The provisional entity's pending routes should now route via the target contact
        if target_dict.get("networking_app_contact_id"):
            try:
                from sauron.routing.routing_log import release_pending_routes
                # Release routes held under the old provisional entity ID
                release_pending_routes(
                    contact_id,
                    target_dict["networking_app_contact_id"],
                    conn,
                )
                _replay_pending_object_routes(contact_id, target_dict["networking_app_contact_id"], conn)
            except Exception:
                logger.exception(f"Failed to release pending routes after merge for {contact_id[:8]}")

        conn.commit()
        return {
            "status": "ok",
            "event_id": event_id,
            "merged_into": target_dict["canonical_name"],
            "merged_contact_id": request.target_contact_id,
        }
    finally:
        conn.close()


@router.post("/provisional/{contact_id}/confirm")
def confirm_provisional_contact(contact_id: str, request: ProvisionalConfirmRequest):
    """Confirm a provisional contact as a real new contact.

    Sets is_confirmed = 1. Optionally updates the name and pushes
    to the Networking App.
    """
    conn = get_connection()
    try:
        # Verify provisional contact exists
        provisional = conn.execute(
            "SELECT * FROM unified_contacts WHERE id = ? AND is_confirmed = 0",
            (contact_id,),
        ).fetchone()
        if not provisional:
            raise HTTPException(404, "Provisional contact not found or already confirmed")

        prov = dict(provisional)

        # Build update fields
        update_fields = ["is_confirmed = 1"]
        update_params = []
        if request.canonical_name:
            update_fields.append("canonical_name = ?")
            update_params.append(request.canonical_name)
        if request.email is not None:
            update_fields.append("email = ?")
            update_params.append(request.email or None)
        if request.phone is not None:
            update_fields.append("phone_number = ?")
            update_params.append(request.phone or None)
        if request.aliases is not None:
            update_fields.append("aliases = ?")
            update_params.append(request.aliases or None)
        update_params.append(contact_id)

        conn.execute(
            f"UPDATE unified_contacts SET {', '.join(update_fields)} WHERE id = ?",
            update_params,
        )

        # If name changed, update claim_entities and event_claims too
        if request.canonical_name:
            conn.execute(
                "UPDATE claim_entities SET entity_name = ? WHERE entity_id = ?",
                (request.canonical_name, contact_id),
            )
            conn.execute(
                "UPDATE event_claims SET subject_name = ? WHERE subject_entity_id = ?",
                (request.canonical_name, contact_id),
            )

        final_name = request.canonical_name or prov["canonical_name"]

        # Run entity confirmation cascade (text rewriting, episode titles, synthesis links, etc.)
        try:
            from sauron.extraction.cascade import cascade_entity_confirmation
            _cascade_names = [prov["canonical_name"]]
            _prov_aliases = prov.get("aliases") or ""
            for _pa in _prov_aliases.split(";"):
                _pa = _pa.strip()
                if _pa:
                    _cascade_names.append(_pa)
            _cascade_stats = cascade_entity_confirmation(
                conn, contact_id, final_name,
                _cascade_names,
                conversation_id=None,
                source="confirm_provisional",
            )
            logger.info(f"Confirm provisional cascade: {_cascade_stats}")
        except Exception:
            logger.exception("Confirm provisional cascade failed (non-fatal)")

        # Learn alias and log correction if name changed
        old_name = prov["canonical_name"]
        if request.canonical_name and old_name.strip().lower() != request.canonical_name.strip().lower():
            try:
                from sauron.extraction.alias_learner import learn_alias
                learn_alias(conn, contact_id, old_name.strip(), request.canonical_name.strip())
                logger.info("Learned alias (confirm): '%s' -> '%s'", old_name, request.canonical_name)
            except Exception:
                logger.exception("Alias learning failed (non-fatal)")
            if _is_transcription_error(old_name.strip(), request.canonical_name.strip()):
                try:
                    conn.execute(
                        """INSERT INTO correction_events
                           (id, conversation_id, error_type, old_value, new_value, correction_source)
                           VALUES (?, ?, 'name_transcription', ?, ?, 'confirm_provisional')""",
                        (str(uuid.uuid4()), prov.get("source_conversation_id") or "",
                         old_name.strip(), request.canonical_name.strip()),
                    )
                except Exception:
                    logger.exception("Correction event logging failed (non-fatal)")

        # Optionally push to Networking App
        if request.push_to_networking_app:
            try:
                import httpx
                from sauron.config import NETWORKING_APP_URL
                resp = httpx.post(
                    f"{NETWORKING_APP_URL}/api/contacts",
                    json={"name": final_name},
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    net_id = data.get("id") or data.get("contact_id")
                    if net_id:
                        conn.execute(
                            "UPDATE unified_contacts SET networking_app_contact_id = ? WHERE id = ?",
                            (str(net_id), contact_id),
                        )
                        logger.info(f"Pushed confirmed contact '{final_name}' to Networking App (id={net_id})")
                        # Release any pending routes held for this entity
                        try:
                            from sauron.routing.routing_log import release_pending_routes
                            release_pending_routes(contact_id, str(net_id), conn)
                            _replay_pending_object_routes(contact_id, str(net_id), conn)
                        except Exception:
                            logger.exception(f"Failed to release pending routes for {contact_id[:8]}")
            except Exception as e:
                logger.warning(f"Failed to push contact to Networking App: {e}")

        conn.commit()
        return {
            "status": "ok",
            "contact_id": contact_id,
            "canonical_name": final_name,
            "is_confirmed": True,
        }
    finally:
        conn.close()


@router.post("/provisional/{contact_id}/dismiss")
def dismiss_provisional_contact(contact_id: str):
    """Dismiss a provisional contact.

    Removes the provisional record and unlinks from claims.
    The name stays in claim_text as unlinked text.
    """
    conn = get_connection()
    try:
        # Verify provisional contact exists
        provisional = conn.execute(
            "SELECT * FROM unified_contacts WHERE id = ? AND is_confirmed = 0",
            (contact_id,),
        ).fetchone()
        if not provisional:
            raise HTTPException(404, "Provisional contact not found or already confirmed")

        # Remove claim_entities links
        conn.execute(
            "DELETE FROM claim_entities WHERE entity_id = ?",
            (contact_id,),
        )

        # Clear subject_entity_id on event_claims (leave subject_name as-is)
        conn.execute(
            "UPDATE event_claims SET subject_entity_id = NULL WHERE subject_entity_id = ?",
            (contact_id,),
        )

        # Mark any held pending_object_routes as dismissed
        conn.execute(
            """UPDATE pending_object_routes
               SET status = 'dismissed', released_at = datetime('now')
               WHERE blocked_on_entity = ? AND status = 'pending'""",
            (contact_id,),
        )

        # Delete the provisional contact
        conn.execute("DELETE FROM unified_contacts WHERE id = ?", (contact_id,))

        conn.commit()
        return {
            "status": "ok",
            "dismissed": dict(provisional)["canonical_name"],
        }
    finally:
        conn.close()


@router.post("/contacts")
def create_contact(request: CreateContactRequest):
    """Create a new confirmed contact directly.

    Creates in unified_contacts with is_confirmed=1.
    Optionally pushes to Networking App.
    """
    from fastapi.responses import JSONResponse

    conn = get_connection()
    try:
        name = request.canonical_name.strip()

        # Fix 6: Duplicate detection
        existing = conn.execute(
            "SELECT id, canonical_name FROM unified_contacts WHERE LOWER(canonical_name) = LOWER(?)",
            (name,)
        ).fetchone()
        if existing:
            return JSONResponse(
                status_code=409,
                content={"detail": f"Contact '{existing['canonical_name']}' already exists", "existing_id": existing["id"]}
            )

        contact_id = str(uuid.uuid4())
        aliases_json = request.aliases or None

        # Fix 1+2: Include organization and title in INSERT
        conn.execute(
            """INSERT INTO unified_contacts
               (id, canonical_name, current_organization, current_title,
                email, phone_number, aliases,
                is_confirmed, source_conversation_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'))""",
            (contact_id, name,
             request.organization or None, request.title or None,
             request.email or None, request.phone or None,
             aliases_json,
             request.source_conversation_id),
        )

        networking_app_contact_id = None

        # Fix 3: Push richer data to Networking App
        if request.push_to_networking_app:
            try:
                import httpx
                from sauron.config import NETWORKING_APP_URL
                payload = {"name": name}
                if request.organization:
                    payload["organization"] = request.organization
                if request.title:
                    payload["title"] = request.title
                if request.email:
                    payload["email"] = request.email
                if request.phone:
                    payload["phone"] = request.phone
                if request.notes:
                    payload["notes"] = request.notes
                resp = httpx.post(
                    f"{NETWORKING_APP_URL}/api/contacts",
                    json=payload,
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    net_id = data.get("id") or data.get("contact_id")
                    if net_id:
                        conn.execute(
                            "UPDATE unified_contacts SET networking_app_contact_id = ? WHERE id = ?",
                            (str(net_id), contact_id),
                        )
                        networking_app_contact_id = str(net_id)
                        logger.info(f"Pushed new contact '{name}' to Networking App (id={net_id})")
            except Exception as e:
                logger.warning(f"Failed to push contact to Networking App: {e}")

        # Fix 5: Run entity confirmation cascade to link existing claims
        try:
            from sauron.extraction.cascade import cascade_entity_confirmation
            cascade_names = [name]
            # Include original extracted name so cascade links claims to the new contact
            if request.original_name and request.original_name.strip().lower() != name.lower():
                cascade_names.append(request.original_name.strip())
            if request.aliases:
                for a in request.aliases.split(";"):
                    a = a.strip()
                    if a:
                        cascade_names.append(a)
            cascade_entity_confirmation(
                conn, contact_id, name, cascade_names,
                conversation_id=request.source_conversation_id,
                source="create_contact",
            )
        except Exception:
            logger.exception("create_contact cascade failed (non-fatal)")

        # Learn alias and log correction if original name differs from canonical
        if request.original_name and request.original_name.strip().lower() != name.lower():
            orig = request.original_name.strip()
            try:
                from sauron.extraction.alias_learner import learn_alias
                learn_alias(conn, contact_id, orig, name)
                logger.info(f"Learned alias: '{orig}' -> '{name}'")
            except Exception:
                logger.exception("Alias learning failed (non-fatal)")
            # Log correction event only for genuine transcription errors (no common words)
            if _is_transcription_error(orig, name):
                try:
                    conn.execute(
                        """INSERT INTO correction_events
                           (id, conversation_id, error_type, old_value, new_value, correction_source)
                           VALUES (?, ?, 'name_transcription', ?, ?, 'create_contact')""",
                        (str(uuid.uuid4()), request.source_conversation_id or '',
                         orig, name),
                    )
                    logger.info(f"Logged name_transcription correction: '{orig}' -> '{name}'")
                except Exception:
                    logger.exception("Correction event logging failed (non-fatal)")

        # Absorb matching provisional contact if one exists
        if request.original_name:
            provisional = conn.execute(
                """SELECT id FROM unified_contacts
                   WHERE LOWER(canonical_name) = LOWER(?) AND is_confirmed = 0 AND id != ?""",
                (request.original_name.strip(), contact_id)
            ).fetchone()
            if provisional:
                prov_id = provisional["id"]
                conn.execute(
                    "UPDATE event_claims SET subject_entity_id = ? WHERE subject_entity_id = ?",
                    (contact_id, prov_id)
                )
                conn.execute(
                    "UPDATE claim_entities SET entity_id = ? WHERE entity_id = ?",
                    (contact_id, prov_id)
                )
                conn.execute(
                    "UPDATE synthesis_entity_links SET resolved_entity_id = ? WHERE resolved_entity_id = ?",
                    (contact_id, prov_id)
                )
                conn.execute("DELETE FROM unified_contacts WHERE id = ?", (prov_id,))
                logger.info(f"Absorbed provisional (id={prov_id[:8]}) into new contact (id={contact_id[:8]})")

        conn.commit()
        return {
            "status": "ok",
            "contact_id": contact_id,
            "canonical_name": name,
            "networking_app_contact_id": networking_app_contact_id,
        }
    finally:
        conn.close()

# -- Duplicate contact detection & networking app validation -----

@router.get("/duplicates")
def detect_duplicate_contacts():
    """Detect duplicate unified_contacts sharing the same networking_app_contact_id.

    For each group of duplicates, validates against the networking app to check
    whether the canonical contact still exists. Returns a report with:
    - sauron_duplicates: groups of rows sharing a networking_app_contact_id
    - networking_app_status: whether each networking_app_contact_id resolves
      to exactly one contact in the networking app
    - recommendations: auto-resolvable vs needs-attention
    """
    conn = get_connection()
    try:
        dup_groups = conn.execute(
            """SELECT networking_app_contact_id, COUNT(*) as cnt
               FROM unified_contacts
               WHERE networking_app_contact_id IS NOT NULL
               GROUP BY networking_app_contact_id
               HAVING cnt > 1
               ORDER BY cnt DESC"""
        ).fetchall()

        if not dup_groups:
            return {"status": "clean", "duplicate_count": 0, "groups": [],
                    "message": "No duplicate contacts found."}

        groups = []
        networking_warnings = []

        for dg in dup_groups:
            naid = dg["networking_app_contact_id"]
            rows = conn.execute(
                """SELECT id, canonical_name, email, is_confirmed,
                       source_conversation_id, created_at
                   FROM unified_contacts
                   WHERE networking_app_contact_id = ?
                   ORDER BY is_confirmed DESC, source_conversation_id IS NOT NULL, created_at""",
                (naid,),
            ).fetchall()

            contacts_list = [dict(r) for r in rows]
            net_status = _validate_networking_app_contact(naid)

            group = {
                "networking_app_contact_id": naid,
                "sauron_count": dg["cnt"],
                "contacts": contacts_list,
                "networking_app_status": net_status,
                "recommendation": "auto_resolve" if net_status["exists"] else "orphaned",
            }
            groups.append(group)

            if net_status.get("warning"):
                networking_warnings.append({
                    "networking_app_contact_id": naid,
                    "warning": net_status["warning"],
                })

        total_extra = sum(g["sauron_count"] - 1 for g in groups)
        return {
            "status": "duplicates_found",
            "duplicate_count": len(groups),
            "total_extra_rows": total_extra,
            "groups": groups,
            "networking_warnings": networking_warnings,
            "message": f"{len(groups)} duplicate group(s) found with {total_extra} extra rows.",
        }
    finally:
        conn.close()


def _validate_networking_app_contact(networking_app_contact_id: str) -> dict:
    """Check whether a networking_app_contact_id resolves to a valid contact."""
    try:
        import httpx
        from sauron.config import NETWORKING_APP_URL
        resp = httpx.get(
            f"{NETWORKING_APP_URL}/api/contacts/{networking_app_contact_id}",
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "exists": True,
                "name": data.get("name") or data.get("canonical_name", "Unknown"),
                "id": data.get("id"),
                "warning": None,
            }
        elif resp.status_code == 404:
            return {
                "exists": False,
                "warning": f"Contact {networking_app_contact_id} not found in networking app (404)",
            }
        else:
            return {
                "exists": False,
                "warning": f"Networking app returned status {resp.status_code}",
            }
    except Exception as e:
        return {
            "exists": False,
            "warning": f"Failed to reach networking app: {str(e)}",
        }



@router.post("/resolve-duplicates")
def resolve_duplicate_contacts():
    """Auto-resolve duplicate unified_contacts by merging into one row per networking_app_contact_id.

    Strategy:
    1. Pick the "best" keeper row: is_confirmed=1 preferred, non-conversation-sourced
       preferred, oldest created_at as tiebreaker.
    2. Merge scalar fields: email, phone, relationships, voice_profile_id, calendar_aliases
       are copied from dupes to keeper where keeper's value is NULL.
    3. Merge aliases via set union.
    4. Re-point ALL foreign key references across all tables to the keeper ID.
    5. Handle claim_entities UNIQUE(claim_id, entity_id, role) constraint by deleting
       dupe rows that would collide before re-pointing.
    6. Log a before/after snapshot for each group to a merge_audit_log table.
    7. Delete the duplicate unified_contacts rows.

    The entire operation runs in one transaction — any error rolls back all changes.
    """
    conn = get_connection()
    try:
        # Ensure audit log table exists
        conn.execute("""CREATE TABLE IF NOT EXISTS merge_audit_log (
            id TEXT PRIMARY KEY,
            networking_app_contact_id TEXT NOT NULL,
            keeper_id TEXT NOT NULL,
            keeper_name TEXT,
            removed_ids TEXT,
            removed_names TEXT,
            fields_merged TEXT,
            fk_updates TEXT,
            created_at DATETIME DEFAULT (datetime('now'))
        )""")

        dup_groups = conn.execute(
            """SELECT networking_app_contact_id
               FROM unified_contacts
               WHERE networking_app_contact_id IS NOT NULL
               GROUP BY networking_app_contact_id
               HAVING COUNT(*) > 1"""
        ).fetchall()

        if not dup_groups:
            return {"status": "clean", "resolved": 0, "message": "No duplicates to resolve."}

        resolved = 0
        details = []

        for dg in dup_groups:
            naid = dg["networking_app_contact_id"]
            rows = conn.execute(
                """SELECT id, canonical_name, aliases, email, phone_number,
                       relationships, voice_profile_id, calendar_aliases,
                       is_confirmed, source_conversation_id, created_at
                   FROM unified_contacts
                   WHERE networking_app_contact_id = ?
                   ORDER BY is_confirmed DESC,
                            source_conversation_id IS NOT NULL,
                            created_at""",
                (naid,),
            ).fetchall()

            if len(rows) < 2:
                continue

            keeper = dict(rows[0])
            dupes = [dict(r) for r in rows[1:]]

            # ── Merge scalar fields (null-fill from dupes) ──
            scalar_fields = ["email", "phone_number", "relationships",
                             "voice_profile_id", "calendar_aliases"]
            fields_merged = []
            for field in scalar_fields:
                if not keeper.get(field):
                    for dupe in dupes:
                        if dupe.get(field):
                            keeper[field] = dupe[field]
                            fields_merged.append(f"{field}={dupe[field]!r} (from {dupe['id'][:8]})")
                            break

            # ── Merge aliases via set union ──
            all_aliases = set()
            for alias_str in [keeper.get("aliases") or ""] + [d.get("aliases") or "" for d in dupes]:
                for a in alias_str.split(";"):
                    a = a.strip()
                    if a:
                        all_aliases.add(a)
            merged_aliases = "; ".join(sorted(all_aliases)) if all_aliases else None

            # ── Update keeper row with merged data ──
            conn.execute(
                """UPDATE unified_contacts
                   SET aliases = ?, email = ?, phone_number = ?,
                       relationships = ?, voice_profile_id = ?,
                       calendar_aliases = ?
                   WHERE id = ?""",
                (merged_aliases, keeper.get("email"), keeper.get("phone_number"),
                 keeper.get("relationships"), keeper.get("voice_profile_id"),
                 keeper.get("calendar_aliases"), keeper["id"]),
            )

            # ── Re-point ALL foreign key references ──
            fk_updates = {}
            for dupe in dupes:
                did = dupe["id"]
                kid = keeper["id"]

                # --- Handle claim_entities UNIQUE constraint ---
                # Find claim_entities rows on dupe that would collide with keeper
                collisions = conn.execute(
                    """SELECT ce_dupe.id
                       FROM claim_entities ce_dupe
                       JOIN claim_entities ce_keep
                         ON ce_dupe.claim_id = ce_keep.claim_id
                        AND ce_dupe.role = ce_keep.role
                       WHERE ce_dupe.entity_id = ?
                         AND ce_keep.entity_id = ?""",
                    (did, kid),
                ).fetchall()
                for col in collisions:
                    conn.execute("DELETE FROM claim_entities WHERE id = ?", (col["id"],))
                    fk_updates["claim_entities_collision_deleted"] = \
                        fk_updates.get("claim_entities_collision_deleted", 0) + 1

                # Table: event_claims.subject_entity_id
                r = conn.execute(
                    "UPDATE event_claims SET subject_entity_id = ? WHERE subject_entity_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["event_claims.subject_entity_id"] = \
                    fk_updates.get("event_claims.subject_entity_id", 0) + r.rowcount

                # Table: event_claims.speaker_id
                r = conn.execute(
                    "UPDATE event_claims SET speaker_id = ? WHERE speaker_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["event_claims.speaker_id"] = \
                    fk_updates.get("event_claims.speaker_id", 0) + r.rowcount

                # Table: claim_entities.entity_id
                r = conn.execute(
                    "UPDATE claim_entities SET entity_id = ? WHERE entity_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["claim_entities.entity_id"] = \
                    fk_updates.get("claim_entities.entity_id", 0) + r.rowcount

                # Table: transcripts.speaker_id
                r = conn.execute(
                    "UPDATE transcripts SET speaker_id = ? WHERE speaker_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["transcripts.speaker_id"] = \
                    fk_updates.get("transcripts.speaker_id", 0) + r.rowcount

                # Table: graph_edges (correct column names: from_entity, to_entity)
                r = conn.execute(
                    "UPDATE graph_edges SET from_entity = ? WHERE from_entity = ?",
                    (kid, did))
                if r.rowcount: fk_updates["graph_edges.from_entity"] = \
                    fk_updates.get("graph_edges.from_entity", 0) + r.rowcount
                r = conn.execute(
                    "UPDATE graph_edges SET to_entity = ? WHERE to_entity = ?",
                    (kid, did))
                if r.rowcount: fk_updates["graph_edges.to_entity"] = \
                    fk_updates.get("graph_edges.to_entity", 0) + r.rowcount

                # Table: synthesis_entity_links.resolved_entity_id
                r = conn.execute(
                    "UPDATE synthesis_entity_links SET resolved_entity_id = ? WHERE resolved_entity_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["synthesis_entity_links"] = \
                    fk_updates.get("synthesis_entity_links", 0) + r.rowcount

                # Table: transcript_annotations.resolved_contact_id
                r = conn.execute(
                    "UPDATE transcript_annotations SET resolved_contact_id = ? WHERE resolved_contact_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["transcript_annotations"] = \
                    fk_updates.get("transcript_annotations", 0) + r.rowcount

                # Table: voice_profiles.contact_id
                r = conn.execute(
                    "UPDATE voice_profiles SET contact_id = ? WHERE contact_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["voice_profiles"] = \
                    fk_updates.get("voice_profiles", 0) + r.rowcount

                # Table: embeddings.contact_id
                r = conn.execute(
                    "UPDATE embeddings SET contact_id = ? WHERE contact_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["embeddings"] = \
                    fk_updates.get("embeddings", 0) + r.rowcount

                # Table: beliefs.entity_id
                r = conn.execute(
                    "UPDATE beliefs SET entity_id = ? WHERE entity_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["beliefs"] = \
                    fk_updates.get("beliefs", 0) + r.rowcount

                # Table: meeting_intentions.target_contact_id
                r = conn.execute(
                    "UPDATE meeting_intentions SET target_contact_id = ? WHERE target_contact_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["meeting_intentions"] = \
                    fk_updates.get("meeting_intentions", 0) + r.rowcount

                # Table: routing_log.entity_id
                r = conn.execute(
                    "UPDATE routing_log SET entity_id = ? WHERE entity_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["routing_log"] = \
                    fk_updates.get("routing_log", 0) + r.rowcount

                # Step I: opportunity_signals and ask_vectors deprecated
                # (zero data, zero writers — FK updates removed)

                # Table: policy_positions.contact_id
                r = conn.execute(
                    "UPDATE policy_positions SET contact_id = ? WHERE contact_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["policy_positions"] = \
                    fk_updates.get("policy_positions", 0) + r.rowcount

                # Table: contact_extraction_preferences.contact_id
                r = conn.execute(
                    "UPDATE contact_extraction_preferences SET contact_id = ? WHERE contact_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["contact_extraction_preferences"] = \
                    fk_updates.get("contact_extraction_preferences", 0) + r.rowcount

                # Table: vocal_baselines.contact_id
                r = conn.execute(
                    "UPDATE vocal_baselines SET contact_id = ? WHERE contact_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["vocal_baselines"] = \
                    fk_updates.get("vocal_baselines", 0) + r.rowcount

                # Table: vocal_features.speaker_id
                r = conn.execute(
                    "UPDATE vocal_features SET speaker_id = ? WHERE speaker_id = ?",
                    (kid, did))
                if r.rowcount: fk_updates["vocal_features"] = \
                    fk_updates.get("vocal_features", 0) + r.rowcount

                # Delete the duplicate row
                conn.execute("DELETE FROM unified_contacts WHERE id = ?", (did,))

            # ── Write audit log ──
            audit_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO merge_audit_log
                   (id, networking_app_contact_id, keeper_id, keeper_name,
                    removed_ids, removed_names, fields_merged, fk_updates)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (audit_id, naid, keeper["id"], keeper["canonical_name"],
                 json.dumps([d["id"] for d in dupes]),
                 json.dumps([d["canonical_name"] for d in dupes]),
                 json.dumps(fields_merged),
                 json.dumps(fk_updates)),
            )

            resolved += 1
            details.append({
                "networking_app_contact_id": naid,
                "kept": keeper["canonical_name"],
                "kept_id": keeper["id"],
                "removed_count": len(dupes),
                "removed": [d["canonical_name"] for d in dupes],
                "fields_merged": fields_merged,
                "fk_updates": fk_updates,
            })

        conn.commit()
        logger.info(f"Resolved {resolved} duplicate contact group(s)")
        return {
            "status": "resolved",
            "resolved": resolved,
            "details": details,
            "message": f"Resolved {resolved} duplicate group(s).",
        }
    finally:
        conn.close()
