"""Contact ID bridge resolution for Sauron → Networking App routing.

Resolves the Networking App contact ID from unified_contacts.networking_app_contact_id.
No HTTP name-string lookups. If the ID is not populated, returns None so the caller
can hold the route as pending_entity.

See Integration Spec v2, Section 11.
"""

import logging
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


def resolve_networking_contact_id(conversation_id: str, conn=None) -> dict:
    """Resolve the primary non-Stephen contact for this conversation.

    Returns dict with:
        - entity_id: unified_contacts.id (Sauron's internal ID)
        - networking_app_contact_id: the Networking App's contact ID (or None)
        - canonical_name: the contact's name
        - resolved: True if networking_app_contact_id is populated

    If no non-Stephen speaker is found, returns None.
    """
    should_close = conn is None
    if conn is None:
        conn = get_connection()

    try:
        # Strategy: find the primary non-Stephen entity linked to claims in this conversation.
        # Look at event_claims with subject_entity_id set, exclude Stephen Andrews.
        row = conn.execute(
            """SELECT uc.id as entity_id,
                      uc.canonical_name,
                      uc.networking_app_contact_id
               FROM event_claims ec
               JOIN unified_contacts uc ON ec.subject_entity_id = uc.id
               WHERE ec.conversation_id = ?
                 AND LOWER(uc.canonical_name) NOT LIKE '%stephen andrews%'
                 AND ec.subject_entity_id IS NOT NULL
               GROUP BY uc.id
               ORDER BY COUNT(*) DESC
               LIMIT 1""",
            (conversation_id,),
        ).fetchone()

        if not row:
            # Fallback: check speaker identities from transcripts
            row = conn.execute(
                """SELECT uc.id as entity_id,
                          uc.canonical_name,
                          uc.networking_app_contact_id
                   FROM transcripts t
                   JOIN unified_contacts uc ON t.speaker_id = uc.id
                   WHERE t.conversation_id = ?
                     AND LOWER(uc.canonical_name) NOT LIKE '%stephen andrews%'
                   GROUP BY uc.id
                   ORDER BY COUNT(*) DESC
                   LIMIT 1""",
                (conversation_id,),
            ).fetchone()

        if not row:
            logger.debug(f"No non-Stephen contact found for conversation {conversation_id[:8]}")
            return None

        result = dict(row)
        result["resolved"] = result["networking_app_contact_id"] is not None
        return result

    finally:
        if should_close:
            conn.close()


def resolve_entity_networking_id(entity_id: str, conn=None) -> str | None:
    """Look up the Networking App contact ID for a specific unified_contacts entity.

    Returns the networking_app_contact_id or None.
    """
    should_close = conn is None
    if conn is None:
        conn = get_connection()

    try:
        row = conn.execute(
            "SELECT networking_app_contact_id FROM unified_contacts WHERE id = ?",
            (entity_id,),
        ).fetchone()
        return row["networking_app_contact_id"] if row else None
    finally:
        if should_close:
            conn.close()
