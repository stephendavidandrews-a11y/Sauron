"""Shared helper functions for the corrections API.

Exported:
  sync_claim_entities_subject — junction table sync (used by 3 external modules)
  _detect_relational_reference — relational name detection (used by cascade.py)
  _check_dynamic_trigger — background analysis trigger
"""
import logging
import re as _re
import uuid

from sauron.api.relational_terms import RELATIONAL_TERMS, PLURAL_TERMS

logger = logging.getLogger(__name__)

RELATIONAL_PATTERNS = [
    _re.compile(r"\b(?:my|his|her|their|\w+'s)\s+(\w+)\b", _re.IGNORECASE),
    _re.compile(r"\b(\w+'s)\s+(\w+)\b", _re.IGNORECASE),
]


def _check_dynamic_trigger(conn):
    """Check if unprocessed corrections exceed threshold and trigger analysis."""
    try:
        latest_amendment_date = conn.execute(
            "SELECT MAX(created_at) FROM prompt_amendments"
        ).fetchone()[0] or "1970-01-01T00:00:00"
        pending = conn.execute(
            "SELECT COUNT(*) FROM correction_events WHERE created_at > ?",
            (latest_amendment_date,)
        ).fetchone()[0]

        DYNAMIC_TRIGGER_THRESHOLD = 25

        if pending >= DYNAMIC_TRIGGER_THRESHOLD:
            from sauron.executor import submit_background_job
            def _run_analysis():
                try:
                    from sauron.learning.amendments import analyze_corrections_and_amend
                    result = analyze_corrections_and_amend()
                    if result:
                        logger.info("Dynamic trigger: generated new amendment from %d corrections", pending)
                except Exception:
                    logger.exception("Dynamic trigger analysis failed")
            submit_background_job(_run_analysis)
    except Exception:
        logger.exception("Dynamic trigger check failed (non-fatal)")


def _detect_relational_reference(claim_text: str, anchor_names: list[str]) -> dict | None:
    """Detect if claim_text contains a relational reference to an anchor person.

    Returns {"anchor_name": ..., "relationship": ..., "phrase": ...} or None.
    Example: "Stephen Weber's son" -> {"anchor_name": "Stephen Weber", "relationship": "son", "phrase": "Stephen Weber's son"}
    """
    if not claim_text or not anchor_names:
        return None

    text_lower = claim_text.lower()

    for anchor in anchor_names:
        if not anchor:
            continue
        anchor_lower = anchor.lower()
        first_name = anchor.split()[0].lower() if anchor else ""

        # Check for "Name's [relation]" patterns
        for possessive in [f"{anchor_lower}'s", f"{first_name}'s"]:
            idx = text_lower.find(possessive)
            if idx == -1:
                continue
            after = text_lower[idx + len(possessive):].strip()
            for term in RELATIONAL_TERMS:
                if after.startswith(term):
                    # Verify it's a word boundary
                    end_pos = len(term)
                    if end_pos >= len(after) or not after[end_pos].isalpha():
                        phrase_start = idx
                        phrase_end = idx + len(possessive) + 1 + end_pos
                        phrase = claim_text[phrase_start:phrase_end].strip()
                        is_plural = term in PLURAL_TERMS
                        return {
                            "anchor_name": anchor,
                            "relationship": term,
                            "is_plural": is_plural,
                            "phrase": phrase,
                        }

        # Check for "my [relation]" pattern (anchor = speaker)
        for pattern in [r"\b(my|his|her|their)\s+(\w+)\b"]:
            for m in _re.finditer(pattern, claim_text, _re.IGNORECASE):
                term = m.group(2).lower()
                if term in RELATIONAL_TERMS:
                    is_plural = term in PLURAL_TERMS
                    return {
                        "anchor_name": anchor,
                        "relationship": term,
                        "is_plural": is_plural,
                        "phrase": m.group(0),
                    }

    return None


def sync_claim_entities_subject(conn, claim_id: str, entity_id: str, entity_name: str, link_source: str = "user", entity_table: str = "unified_contacts"):
    """Sync the claim_entities junction table for a subject role.

    Source of truth sync rule: whenever claim_entities changes for a claim,
    update subject_entity_id on event_claims to match the primary role='subject'
    entity. There must never be drift between the two.
    """
    # Check if this entity is already linked to this claim
    existing = conn.execute(
        "SELECT id FROM claim_entities WHERE claim_id = ? AND entity_id = ?",
        (claim_id, entity_id),
    ).fetchone()

    if existing:
        # Already linked — just update the name/source
        conn.execute(
            "UPDATE claim_entities SET entity_name = ?, link_source = ? WHERE id = ?",
            (entity_name, link_source, existing["id"]),
        )
    else:
        # Check if there's already a subject AND it's model-linked (auto).
        # If so, replace it. If user-linked, ADD alongside it.
        model_subject = conn.execute(
            "SELECT id FROM claim_entities WHERE claim_id = ? AND role = 'subject' AND link_source = 'model'",
            (claim_id,),
        ).fetchone()
        if model_subject:
            # Replace auto-linked subject with user-linked one
            conn.execute("DELETE FROM claim_entities WHERE id = ?", (model_subject["id"],))

        # Insert new entry
        conn.execute(
            """INSERT INTO claim_entities
               (id, claim_id, entity_id, entity_name, role, confidence, link_source, entity_table)
               VALUES (?, ?, ?, ?, 'subject', NULL, ?, ?)""",
            (str(uuid.uuid4()), claim_id, entity_id, entity_name, link_source, entity_table),
        )

    # Sync event_claims.subject_entity_id to the FIRST user-linked entity, or most recent
    first_subject = conn.execute(
        """SELECT entity_id, entity_name FROM claim_entities
           WHERE claim_id = ? AND role = 'subject'
           ORDER BY link_source = 'user' DESC, created_at ASC LIMIT 1""",
        (claim_id,),
    ).fetchone()
    if first_subject:
        conn.execute(
            "UPDATE event_claims SET subject_entity_id = ?, subject_name = ? WHERE id = ?",
            (first_subject["entity_id"], first_subject["entity_name"], claim_id),
        )
