"""
sauron/learning/compare.py

Extraction version comparison — compares new extraction against
previous extraction of the same conversation to measure whether
amendments actually improve extraction quality.
"""

from __future__ import annotations

import difflib
import json
import logging
import uuid
from datetime import datetime

from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)


def compare_extractions(
    conversation_id: str,
    old_extraction_id: str,
    new_extraction_id: str,
) -> dict:
    """Compare two extractions of the same conversation.

    Loads claims from both extractions, uses fuzzy text matching to identify
    reproduced/missed/new claims. Checks correction_events to identify
    whether previously-corrected issues are resolved.

    Returns comparison stats dict and stores in reprocessing_comparisons table.
    """
    conn = get_connection()
    try:
        # Load extraction JSONs
        old_ext = conn.execute(
            "SELECT extraction_json, created_at FROM extractions WHERE id = ?",
            (old_extraction_id,),
        ).fetchone()
        new_ext = conn.execute(
            "SELECT extraction_json, created_at FROM extractions WHERE id = ?",
            (new_extraction_id,),
        ).fetchone()

        if not old_ext or not new_ext:
            logger.warning("Missing extraction(s) for comparison: old=%s new=%s",
                           old_extraction_id, new_extraction_id)
            return {}

        # Parse claims from extraction JSON
        old_claims = _extract_claims_from_json(old_ext["extraction_json"])
        new_claims = _extract_claims_from_json(new_ext["extraction_json"])

        # Match claims by text similarity
        matched_old = set()
        matched_new = set()
        matches = []

        for i, old_claim in enumerate(old_claims):
            best_ratio = 0
            best_j = -1
            old_text = old_claim.get("claim_text", "")

            for j, new_claim in enumerate(new_claims):
                if j in matched_new:
                    continue
                new_text = new_claim.get("claim_text", "")
                ratio = difflib.SequenceMatcher(
                    None, old_text.lower(), new_text.lower()
                ).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_j = j

            if best_ratio > 0.7 and best_j >= 0:
                matched_old.add(i)
                matched_new.add(best_j)
                matches.append({
                    "old_index": i,
                    "new_index": best_j,
                    "similarity": round(best_ratio, 3),
                    "old_text": old_claims[i].get("claim_text", ""),
                    "new_text": new_claims[best_j].get("claim_text", ""),
                })

        claims_reproduced = len(matches)
        claims_missed = len(old_claims) - len(matched_old)
        claims_new = len(new_claims) - len(matched_new)

        # Check correction events for this conversation
        corrections = conn.execute(
            """SELECT ce.*, ec.claim_text as corrected_claim_text
               FROM correction_events ce
               LEFT JOIN event_claims ec ON ce.claim_id = ec.id
               WHERE ce.conversation_id = ?
               ORDER BY ce.created_at""",
            (conversation_id,),
        ).fetchall()

        corrections_resolved = 0
        corrections_regressed = 0
        correction_details = []

        for corr in corrections:
            corr = dict(corr)
            error_type = corr.get("error_type", "")
            old_value = corr.get("old_value", "")
            new_value = corr.get("new_value", "")
            claim_text = corr.get("corrected_claim_text", "")

            if not claim_text:
                continue

            # Find the matching new claim
            best_match = None
            best_ratio = 0
            for j, new_claim in enumerate(new_claims):
                ratio = difflib.SequenceMatcher(
                    None,
                    claim_text.lower(),
                    new_claim.get("claim_text", "").lower(),
                ).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = new_claim

            if best_match and best_ratio > 0.6:
                # Check if the correction is reflected in the new extraction
                resolved = _check_correction_resolved(
                    error_type, old_value, new_value, best_match
                )
                if resolved:
                    corrections_resolved += 1
                else:
                    corrections_regressed += 1

                correction_details.append({
                    "error_type": error_type,
                    "resolved": resolved,
                    "match_ratio": round(best_ratio, 3),
                })

        # Get current amendment version
        amendment_row = conn.execute(
            """SELECT version FROM prompt_amendments
               WHERE active = TRUE
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        amendment_version = amendment_row["version"] if amendment_row else None

        # Build comparison JSON
        comparison_json = json.dumps({
            "matches": matches[:20],  # limit stored detail
            "missed_claims": [
                old_claims[i].get("claim_text", "")
                for i in range(len(old_claims)) if i not in matched_old
            ][:10],
            "new_claims": [
                new_claims[j].get("claim_text", "")
                for j in range(len(new_claims)) if j not in matched_new
            ][:10],
            "correction_details": correction_details,
        })

        # Store comparison
        comparison_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO reprocessing_comparisons
               (id, conversation_id, old_extraction_id, new_extraction_id,
                amendment_version, claims_reproduced, claims_missed,
                claims_new, corrections_resolved, corrections_regressed,
                comparison_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                comparison_id,
                conversation_id,
                old_extraction_id,
                new_extraction_id,
                amendment_version,
                claims_reproduced,
                claims_missed,
                claims_new,
                corrections_resolved,
                corrections_regressed,
                comparison_json,
            ),
        )
        conn.commit()

        result = {
            "comparison_id": comparison_id,
            "claims_reproduced": claims_reproduced,
            "claims_missed": claims_missed,
            "claims_new": claims_new,
            "corrections_resolved": corrections_resolved,
            "corrections_regressed": corrections_regressed,
            "amendment_version": amendment_version,
        }

        logger.info(
            "Extraction comparison for %s: %d reproduced, %d missed, "
            "%d new, %d corrections resolved, %d regressed",
            conversation_id, claims_reproduced, claims_missed,
            claims_new, corrections_resolved, corrections_regressed,
        )

        return result

    except Exception:
        logger.exception("Extraction comparison failed for %s", conversation_id)
        return {}
    finally:
        conn.close()


def _extract_claims_from_json(extraction_json: str) -> list[dict]:
    """Extract claim objects from an extraction JSON blob."""
    if not extraction_json:
        return []
    try:
        data = json.loads(extraction_json)
    except (json.JSONDecodeError, TypeError):
        return []

    claims = []

    # Handle different extraction JSON structures
    if isinstance(data, dict):
        # Standard structure: {episodes: [{claims: [...]}]}
        for episode in data.get("episodes", []):
            for claim in episode.get("claims", []):
                claims.append(claim)
        # Also check top-level claims
        for claim in data.get("claims", []):
            claims.append(claim)
    elif isinstance(data, list):
        # List of claims directly
        claims = data

    return claims


def _check_correction_resolved(
    error_type: str,
    old_value: str,
    new_value: str,
    new_claim: dict,
) -> bool:
    """Check if a specific correction is reflected in the new extraction.

    Returns True if the new extraction appears to have the corrected value,
    False if it still has the old (wrong) value.
    """
    if not error_type or not new_claim:
        return False

    # Map error types to claim fields
    field_map = {
        "wrong_modality": "modality",
        "wrong_claim_type": "claim_type",
        "wrong_confidence": "confidence",
        "overstated_position": "claim_text",
        "wrong_commitment_direction": "direction",
        "wrong_commitment_firmness": "firmness",
        "bad_commitment_extraction": "claim_text",
        "claim_text_edited": "claim_text",
    }

    field = field_map.get(error_type)
    if not field:
        return False  # Can't check unknown error types

    current_value = str(new_claim.get(field, "")).lower()
    corrected_lower = str(new_value).lower() if new_value else ""
    old_lower = str(old_value).lower() if old_value else ""

    if corrected_lower and corrected_lower in current_value:
        return True  # New extraction has the corrected value
    if old_lower and old_lower in current_value:
        return False  # New extraction still has the old (wrong) value

    return False  # Inconclusive
