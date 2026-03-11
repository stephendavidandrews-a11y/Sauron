"""Enhanced daily intelligence brief API endpoints.

Endpoints:
  GET /brief/today                  - Full daily intelligence for the Today page
  GET /brief/person/{contact_id}    - Full person brief for the Prep page
  GET /brief/person/by-name/{name}  - Person brief by canonical name lookup
"""

import json
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brief", tags=["brief"])


def _get_stephen_contact_id(conn) -> str | None:
    """Resolve Stephen Andrews' unified_contacts ID."""
    row = conn.execute(
        "SELECT id FROM unified_contacts WHERE canonical_name = 'Stephen Andrews' LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row) if row else {}


def _rows_to_dicts(rows) -> list[dict]:
    """Convert a list of sqlite3.Row objects to a list of dicts."""
    return [dict(r) for r in rows]


def _parse_json_field(value: str | None):
    """Safely parse a JSON string field, returning None on failure."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


@router.get("/today")
async def get_today_brief():
    """Enhanced daily intelligence endpoint.

    Returns everything the Today page needs: conversations, review counts,
    beliefs, commitments, unresolved speakers, and recent activity.
    """
    now = datetime.now()
    today_str = date.today().isoformat()
    seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
    thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()
    mode = "morning" if now.hour < 13 else "evening"

    conn = get_connection()
    try:
        stephen_id = _get_stephen_contact_id(conn)

        # Conversations captured today with episode and claim counts
        conversations_today = conn.execute(
            """SELECT
                c.id,
                c.source,
                c.title,
                c.captured_at,
                c.duration_seconds,
                c.context_classification,
                c.processing_status,
                c.manual_note,
                c.reviewed_at,
                (SELECT COUNT(*) FROM event_episodes ee WHERE ee.conversation_id = c.id) as episode_count,
                (SELECT COUNT(*) FROM event_claims ec WHERE ec.conversation_id = c.id) as claim_count
            FROM conversations c
            WHERE date(c.captured_at) = ?
            ORDER BY c.captured_at DESC""",
            (today_str,),
        ).fetchall()

        # Needs review: completed but not yet reviewed
        needs_review_count = conn.execute(
            """SELECT COUNT(*) as n FROM conversations
               WHERE processing_status = 'completed' AND reviewed_at IS NULL"""
        ).fetchone()["n"]

        # Pending and processing counts
        pending_count = conn.execute(
            "SELECT COUNT(*) as n FROM conversations WHERE processing_status = 'pending'"
        ).fetchone()["n"]

        processing_count = conn.execute(
            "SELECT COUNT(*) as n FROM conversations WHERE processing_status = 'processing'"
        ).fetchone()["n"]

        # Recent beliefs (last 7, joined with contacts for entity name)
        recent_beliefs = conn.execute(
            """SELECT b.id, b.entity_type, b.entity_id, b.belief_key, b.belief_summary,
                      b.status, b.confidence, b.support_count, b.contradiction_count,
                      b.first_observed_at, b.last_confirmed_at, b.last_changed_at,
                      uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               ORDER BY b.last_changed_at DESC
               LIMIT 7""",
        ).fetchall()

        # Contested beliefs
        contested_beliefs = conn.execute(
            """SELECT b.id, b.entity_type, b.entity_id, b.belief_key, b.belief_summary,
                      b.confidence, b.support_count, b.contradiction_count,
                      b.last_changed_at,
                      uc.canonical_name as entity_name
               FROM beliefs b
               LEFT JOIN unified_contacts uc ON b.entity_id = uc.id
               WHERE b.status = 'contested'
               ORDER BY b.last_changed_at DESC
               LIMIT 5""",
        ).fetchall()

        # Commitment claims from the last 30 days
        all_commitments = conn.execute(
            """SELECT ec.id, ec.claim_text, ec.subject_entity_id, ec.subject_name,
                      ec.speaker_id, ec.confidence, ec.evidence_quote, ec.created_at,
                      c.captured_at as conversation_date, c.source as conversation_source
               FROM event_claims ec
               JOIN conversations c ON c.id = ec.conversation_id
               WHERE ec.claim_type = 'commitment'
                 AND date(ec.created_at) >= ?
               ORDER BY ec.created_at DESC""",
            (thirty_days_ago,),
        ).fetchall()

        my_commitments = []
        their_commitments = []
        for cm in all_commitments:
            cm_dict = dict(cm)
            is_mine = False
            if stephen_id and (cm_dict["speaker_id"] == stephen_id or cm_dict["subject_entity_id"] == stephen_id):
                is_mine = True
            elif cm_dict["subject_name"] and "stephen" in cm_dict["subject_name"].lower():
                is_mine = True

            if is_mine and len(my_commitments) < 10:
                my_commitments.append(cm_dict)
            elif not is_mine and len(their_commitments) < 10:
                their_commitments.append(cm_dict)

        # Unresolved speakers
        unresolved_speakers = conn.execute(
            """SELECT vml.id, vml.conversation_id, vml.speaker_label,
                      vml.similarity_score, vml.match_method, vml.created_at,
                      c.captured_at, c.source
               FROM voice_match_log vml
               JOIN conversations c ON c.id = vml.conversation_id
               WHERE vml.match_method = 'unmatched'
                 AND vml.was_correct IS NULL
               ORDER BY vml.created_at DESC
               LIMIT 10""",
        ).fetchall()

        # Recent conversations (last 5 from past 7 days)
        recent_conversations = conn.execute(
            """SELECT
                c.id,
                c.source,
                c.captured_at,
                c.duration_seconds,
                c.context_classification,
                c.processing_status,
                c.reviewed_at,
                c.manual_note
            FROM conversations c
            WHERE date(c.captured_at) >= ?
            ORDER BY c.captured_at DESC
            LIMIT 5""",
            (seven_days_ago,),
        ).fetchall()

        return {
            "mode": mode,
            "date": today_str,
            "conversations_today": _rows_to_dicts(conversations_today),
            "needs_review_count": needs_review_count,
            "pending_count": pending_count,
            "processing_count": processing_count,
            "recent_beliefs": _rows_to_dicts(recent_beliefs),
            "contested_beliefs": _rows_to_dicts(contested_beliefs),
            "my_commitments": my_commitments,
            "their_commitments": their_commitments,
            "unresolved_speakers": _rows_to_dicts(unresolved_speakers),
            "recent_conversations": _rows_to_dicts(recent_conversations),
        }
    finally:
        conn.close()


def _build_person_brief(contact_id: str) -> dict:
    """Build the full person brief payload for a given contact_id."""
    conn = get_connection()
    try:
        # Contact record
        contact_row = conn.execute(
            """SELECT id, canonical_name, email, phone_number, aliases, relationships,
                      voice_profile_id, is_confirmed, networking_app_contact_id,
                      calendar_aliases, created_at
               FROM unified_contacts
               WHERE id = ?""",
            (contact_id,),
        ).fetchone()

        if not contact_row:
            raise HTTPException(status_code=404, detail=f"Contact {contact_id} not found")

        contact = dict(contact_row)

        # Beliefs for this contact
        beliefs = conn.execute(
            """SELECT id, entity_type, entity_id, belief_key, belief_summary,
                      status, confidence, support_count, contradiction_count,
                      first_observed_at, last_confirmed_at, last_changed_at
               FROM beliefs
               WHERE entity_id = ?
               ORDER BY confidence DESC""",
            (contact_id,),
        ).fetchall()

        # Recent claims involving this contact (as subject or speaker)
        recent_claims = conn.execute(
            """SELECT ec.id, ec.claim_type, ec.claim_text, ec.confidence,
                      ec.modality, ec.evidence_quote, ec.subject_name,
                      ec.speaker_id, ec.subject_entity_id, ec.polarity,
                      ec.stability, ec.importance, ec.created_at,
                      c.source as conversation_source, c.captured_at as conversation_date
               FROM event_claims ec
               JOIN conversations c ON c.id = ec.conversation_id
               WHERE ec.subject_entity_id = ? OR ec.speaker_id = ?
               ORDER BY ec.created_at DESC
               LIMIT 20""",
            (contact_id, contact_id),
        ).fetchall()

        # Commitment claims involving this contact
        commitments = conn.execute(
            """SELECT ec.id, ec.claim_text, ec.confidence, ec.evidence_quote,
                      ec.subject_name, ec.speaker_id, ec.subject_entity_id,
                      ec.created_at,
                      c.source as conversation_source, c.captured_at as conversation_date
               FROM event_claims ec
               JOIN conversations c ON c.id = ec.conversation_id
               WHERE ec.claim_type = 'commitment'
                 AND (ec.subject_entity_id = ? OR ec.speaker_id = ?)
               ORDER BY ec.created_at DESC
               LIMIT 10""",
            (contact_id, contact_id),
        ).fetchall()

        # Recent interactions: conversations where this contact is a speaker
        recent_interactions = conn.execute(
            """SELECT DISTINCT c.id, c.captured_at, c.source, c.duration_seconds
               FROM conversations c
               JOIN transcripts t ON t.conversation_id = c.id
               WHERE t.speaker_id = ?
               ORDER BY c.captured_at DESC
               LIMIT 10""",
            (contact_id,),
        ).fetchall()

        # Graph connections
        graph_connections = conn.execute(
            """SELECT id, from_entity, from_type, to_entity, to_type,
                      edge_type, strength, source_conversation_id,
                      observed_at, notes
               FROM graph_edges
               WHERE from_entity = ? OR to_entity = ?
               ORDER BY observed_at DESC
               LIMIT 20""",
            (contact_id, contact_id),
        ).fetchall()

        # Total interaction count
        interaction_count_row = conn.execute(
            """SELECT COUNT(DISTINCT c.id) as n
               FROM conversations c
               JOIN transcripts t ON t.conversation_id = c.id
               WHERE t.speaker_id = ?""",
            (contact_id,),
        ).fetchone()
        interaction_count = interaction_count_row["n"] if interaction_count_row else 0

        # Last interaction date
        last_interaction_row = conn.execute(
            """SELECT MAX(c.captured_at) as last_date
               FROM conversations c
               JOIN transcripts t ON t.conversation_id = c.id
               WHERE t.speaker_id = ?""",
            (contact_id,),
        ).fetchone()
        last_interaction = last_interaction_row["last_date"] if last_interaction_row else None

        # Relationship data (parse JSON from unified_contacts.relationships)
        relationship_data = _parse_json_field(contact.get("relationships"))

        # What changed: beliefs modified in the last 7 days
        seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
        what_changed = conn.execute(
            """SELECT id, belief_key, belief_summary, status, confidence,
                      support_count, contradiction_count,
                      last_changed_at, last_confirmed_at
               FROM beliefs
               WHERE entity_id = ?
                 AND date(last_changed_at) >= ?
               ORDER BY last_changed_at DESC""",
            (contact_id, seven_days_ago),
        ).fetchall()

        return {
            "contact": contact,
            "beliefs": _rows_to_dicts(beliefs),
            "recent_claims": _rows_to_dicts(recent_claims),
            "commitments": _rows_to_dicts(commitments),
            "recent_interactions": _rows_to_dicts(recent_interactions),
            "graph_connections": _rows_to_dicts(graph_connections),
            "interaction_count": interaction_count,
            "last_interaction": last_interaction,
            "relationship_data": relationship_data,
            "what_changed": _rows_to_dicts(what_changed),
        }
    finally:
        conn.close()


@router.get("/person/by-name/{name}")
async def get_person_brief_by_name(name: str):
    """Full person brief by canonical name (case-insensitive match).

    Looks up the contact using a LIKE match against canonical_name,
    then delegates to the standard person brief builder.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM unified_contacts WHERE canonical_name LIKE ? LIMIT 1",
            (name,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"No contact found matching name '{name}'")

    return _build_person_brief(row["id"])


@router.get("/person/{contact_id}")
async def get_person_brief(contact_id: str):
    """Full person brief for the Prep page.

    Returns contact details, beliefs, claims, commitments, interactions,
    graph connections, and recent changes for a specific contact.
    """
    return _build_person_brief(contact_id)
