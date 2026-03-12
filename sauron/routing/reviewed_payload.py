"""Build routing payload from reviewed DB truth.

Used by mark_reviewed to route corrected data to downstream apps,
instead of routing the original (pre-review) extraction JSON.
"""

import json
import logging
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


def build_reviewed_payload(conversation_id: str) -> dict:
    """Assemble routing payload from reviewed claims, entities, and beliefs.

    Returns dict in the shape route_extraction expects:
    {"triage": {...}, "claims": {...}, "synthesis": {...}}
    """
    conn = get_connection()
    try:
        # Load triage (pass 1 — usually not corrected by review)
        triage_row = conn.execute(
            "SELECT extraction_json FROM extractions WHERE conversation_id = ? AND pass_number = 1 ORDER BY created_at DESC",
            (conversation_id,),
        ).fetchone()
        triage = json.loads(triage_row["extraction_json"]) if triage_row else {}

        # Load REVIEWED claims — exclude dismissed, include corrected
        claims_rows = conn.execute(
            """SELECT ec.*, uc.canonical_name as linked_entity_name
               FROM event_claims ec
               LEFT JOIN unified_contacts uc ON ec.subject_entity_id = uc.id
               WHERE ec.conversation_id = ?
                 AND (ec.review_status IS NULL
                      OR ec.review_status NOT IN ('dismissed'))
                 AND ec.confidence > 0""",
            (conversation_id,),
        ).fetchall()

        # Load memory_writes and new_contacts from claims pass (pass 2)
        claims_pass_row = conn.execute(
            "SELECT extraction_json FROM extractions WHERE conversation_id = ? AND pass_number = 2 ORDER BY created_at DESC",
            (conversation_id,),
        ).fetchone()
        claims_pass_data = json.loads(claims_pass_row["extraction_json"]) if claims_pass_row else {}

        memory_writes = claims_pass_data.get("memory_writes", [])
        new_contacts = claims_pass_data.get("new_contacts_mentioned", [])

        # Build claims list and commitment routing
        claims_list = []
        my_commitments = []
        contact_commitments = []
        scheduling_leads = []

        for row in claims_rows:
            cd = dict(row)
            claims_list.append({
                "id": cd["id"],
                "claim_type": cd["claim_type"],
                "claim_text": cd["claim_text"],
                "subject_name": cd.get("linked_entity_name") or cd.get("subject_name", ""),
                "subject_entity_id": cd.get("subject_entity_id"),
                "confidence": cd.get("confidence", 0.8),
                "importance": cd.get("importance", 0.5),
                "evidence_quote": cd.get("evidence_quote", ""),
                "firmness": cd.get("firmness"),
                "direction": cd.get("direction"),
                "time_horizon": cd.get("time_horizon"),
            })

            # Build commitment routing from claim-level metadata
            if cd["claim_type"] == "commitment":
                firmness = cd.get("firmness", "intentional")
                direction = cd.get("direction", "owed_by_me")

                record = {
                    "description": cd["claim_text"],
                    "original_words": cd.get("evidence_quote", ""),
                    "resolved_date": cd.get("time_horizon"),
                    "confidence": cd.get("confidence", 0.8),
                    "direction": direction,
                    "source_claim_id": cd["id"],
                }

                if firmness == "social":
                    scheduling_leads.append({
                        "contact_name": cd.get("subject_name", ""),
                        "description": cd["claim_text"],
                        "original_words": cd.get("evidence_quote", ""),
                        "timeframe": cd.get("time_horizon"),
                    })
                elif firmness == "tentative":
                    pass  # Claim only — no downstream record
                else:
                    # Concrete or intentional
                    if direction in ("owed_by_me", "mutual"):
                        my_commitments.append(record)
                    else:
                        contact_commitments.append(record)

        claims_payload = {
            "claims": claims_list,
            "memory_writes": memory_writes,
            "new_contacts_mentioned": new_contacts,
        }

        # Load synthesis (pass 3) for non-commitment fields
        synth_row = conn.execute(
            "SELECT extraction_json FROM extractions WHERE conversation_id = ? AND pass_number = 3 ORDER BY created_at DESC",
            (conversation_id,),
        ).fetchone()
        synthesis = json.loads(synth_row["extraction_json"]) if synth_row else {}

        # Override synthesis commitment/scheduling fields with reviewed truth
        synthesis["my_commitments"] = my_commitments
        synthesis["contact_commitments"] = contact_commitments
        existing_leads = synthesis.get("scheduling_leads", [])
        synthesis["scheduling_leads"] = scheduling_leads + existing_leads

        return {
            "triage": triage,
            "claims": claims_payload,
            "synthesis": synthesis,
        }
    finally:
        conn.close()
