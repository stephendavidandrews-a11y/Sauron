"""
sauron/learning/amendments.py

Iterative learning from extraction corrections.

Watches the extraction_corrections table for patterns in user feedback,
generates prompt amendments that improve future extractions, and manages
per-contact extraction preferences.

v2: Added EMA decay weighting, amendment effectiveness tracking,
    amendment staleness detection.

FIXED: Column names aligned to actual DB schema:
  - extraction_corrections has: correction_type, original_value, corrected_value
    (no field_path, old_value, new_value, notes, processed_into_amendment)
  - prompt_amendments.version is TEXT ("v1", "v2", ...), not INT
  - prompt_amendments has no correction_ids or patterns_addressed columns
    -> these are stored inside source_analysis as JSON
  - unified_contacts uses canonical_name, not display_name
  - transcripts uses speaker_id, not speaker_contact_id
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

import anthropic

from sauron.config import TRIAGE_MODEL
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

_AMENDMENT_MODEL = "claude-sonnet-4-6"  # was Haiku — Sonnet writes better rules
# Generalization gating thresholds (per Iterative_Improvement_Spec)
_FAST_TYPES = {
    "wrong_modality", "wrong_claim_type", "wrong_confidence",
    "bad_commitment_extraction", "overstated_position",
}
_FAST_THRESHOLD = 3
_SLOW_THRESHOLD = 5
_EMA_HALFLIFE_DAYS = 30
_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=2)
    return _client


# ---------------------------------------------------------------------------
# Active amendment retrieval
# ---------------------------------------------------------------------------


def get_active_amendment() -> str | None:
    """Return the currently active global prompt amendment text, or None.

    Only one amendment version is active at a time (active=TRUE).
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT amendment_text FROM prompt_amendments
            WHERE active = TRUE
            ORDER BY created_at DESC
            LIMIT 1
            """,
        ).fetchone()
        return row["amendment_text"] if row else None
    finally:
        conn.close()


def _get_active_amendment_row(conn) -> dict | None:
    """Return the full active amendment row, or None."""
    row = conn.execute(
        """
        SELECT * FROM prompt_amendments
        WHERE active = TRUE
        ORDER BY created_at DESC
        LIMIT 1
        """,
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Correction analysis and amendment generation
# ---------------------------------------------------------------------------


def _get_unprocessed_corrections(conn) -> list[dict]:
    """Fetch correction events not yet folded into an amendment.

    Uses correction_events table (per Iterative_Improvement_Spec).
    Falls back to extraction_corrections if correction_events is empty.
    """
    latest = conn.execute(
        "SELECT MAX(created_at) AS latest FROM prompt_amendments"
    ).fetchone()
    cutoff = latest["latest"] if latest and latest["latest"] else "1970-01-01T00:00:00"

    # Try correction_events first (new table)
    rows = conn.execute(
        """
        SELECT ce.id, ce.conversation_id, ce.error_type as correction_type,
               ce.old_value as original_value, ce.new_value as corrected_value,
               ce.created_at as corrected_at, ce.user_feedback,
               ce.episode_id, ce.claim_id, ce.belief_id
        FROM correction_events ce
        WHERE ce.created_at > ?
        ORDER BY ce.created_at
        """,
        (cutoff,),
    ).fetchall()

    if rows:
        return [dict(r) for r in rows]

    # Fallback to legacy table
    rows = conn.execute(
        """
        SELECT ec.id, ec.conversation_id, ec.correction_type,
               ec.original_value, ec.corrected_value, ec.corrected_at
        FROM extraction_corrections ec
        WHERE ec.corrected_at > ?
        ORDER BY ec.corrected_at
        """,
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def _group_corrections(
    corrections: list[dict], decay_halflife_days: int = _EMA_HALFLIFE_DAYS
) -> dict:
    """Group corrections by type with EMA decay weighting.

    Recent corrections count ~1.0. Corrections from 30 days ago count ~0.5.
    Corrections from 60 days ago count ~0.25.

    Returns dict with:
      - weighted_counts: {error_type: float}  (for gating decisions)
      - groups: {error_type: [corrections]}   (for prompt examples)
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    weighted_counts: dict[str, float] = defaultdict(float)

    now = datetime.now(timezone.utc)

    for c in corrections:
        key = c.get("correction_type", "unknown")
        groups[key].append(c)

        # Compute age-based weight
        corrected_at = c.get("corrected_at") or c.get("created_at")
        if corrected_at:
            try:
                if isinstance(corrected_at, str):
                    # Handle both ISO formats
                    corrected_dt = datetime.fromisoformat(
                        corrected_at.replace("Z", "+00:00")
                    )
                    if corrected_dt.tzinfo is None:
                        corrected_dt = corrected_dt.replace(tzinfo=timezone.utc)
                else:
                    corrected_dt = now  # fallback
                age_days = max(0, (now - corrected_dt).total_seconds() / 86400)
                weight = 0.5 ** (age_days / decay_halflife_days)
            except (ValueError, TypeError):
                weight = 1.0  # fallback: treat as recent
        else:
            weight = 1.0

        # A4: Boost weight for corrections with explicit user feedback
        if c.get("user_feedback"):
            weight *= 2.0
        weighted_counts[key] += weight

    return {
        "weighted_counts": dict(weighted_counts),
        "groups": dict(groups),
    }


# ---------------------------------------------------------------------------
# Feature 2: Amendment effectiveness tracking
# ---------------------------------------------------------------------------


def _compute_amendment_effectiveness(conn) -> list[dict]:
    """For each active amendment rule's target error types, compare correction
    rates before vs. after the amendment was activated.

    Returns list of {error_type, corrections_before, corrections_after,
    period_days, effectiveness, rule_text_snippet}.
    """
    active = _get_active_amendment_row(conn)
    if not active:
        return []

    amendment_id = active["id"]
    created_at = active["created_at"]
    if not created_at:
        return []

    # Parse source_analysis to get targeted error types
    source_analysis = {}
    if active.get("source_analysis"):
        try:
            source_analysis = json.loads(active["source_analysis"])
        except (json.JSONDecodeError, TypeError):
            pass

    patterns = source_analysis.get("patterns_addressed", [])
    if not patterns:
        return []

    # Calculate period: time since amendment creation
    try:
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        period_days = max(1, int((now - created_dt).total_seconds() / 86400))
    except (ValueError, TypeError):
        period_days = 7  # fallback

    results = []
    for error_type in patterns:
        # Count corrections AFTER amendment
        after_row = conn.execute(
            """SELECT COUNT(*) as cnt FROM correction_events
               WHERE error_type = ? AND created_at > ?""",
            (error_type, created_at),
        ).fetchone()
        corrections_after = after_row["cnt"] if after_row else 0

        # Count corrections in equivalent period BEFORE amendment
        before_start = (created_dt - (now - created_dt)).isoformat()
        before_row = conn.execute(
            """SELECT COUNT(*) as cnt FROM correction_events
               WHERE error_type = ? AND created_at > ? AND created_at <= ?""",
            (error_type, before_start, created_at),
        ).fetchone()
        corrections_before = before_row["cnt"] if before_row else 0

        # Determine effectiveness
        total = corrections_before + corrections_after
        if total < 3:
            effectiveness = "insufficient_data"
        elif corrections_after < corrections_before * 0.5:
            effectiveness = "effective"
        elif corrections_after >= corrections_before * 0.8:
            effectiveness = "ineffective"
        else:
            effectiveness = "mixed"

        result = {
            "error_type": error_type,
            "corrections_before": corrections_before,
            "corrections_after": corrections_after,
            "period_days": period_days,
            "effectiveness": effectiveness,
        }
        results.append(result)

        # Store in DB
        try:
            conn.execute(
                """INSERT INTO amendment_effectiveness
                   (id, amendment_id, amendment_version, error_type,
                    corrections_before, corrections_after, period_days,
                    effectiveness)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    amendment_id,
                    active.get("version", ""),
                    error_type,
                    corrections_before,
                    corrections_after,
                    period_days,
                    effectiveness,
                ),
            )
        except Exception:
            logger.debug("Failed to store effectiveness record (non-fatal)")

    try:
        conn.commit()
    except Exception:
        pass

    return results


# ---------------------------------------------------------------------------
# Feature 3: Amendment staleness detection
# ---------------------------------------------------------------------------


def _detect_stale_rules(conn, current_amendment_id: str = None) -> list[dict]:
    """Identify error types addressed by the current amendment that have
    had ZERO corrections in the last 60 days.

    Returns list of {error_type, days_since_last_correction, rule_status}.
    """
    active = _get_active_amendment_row(conn) if not current_amendment_id else None
    if current_amendment_id:
        row = conn.execute(
            "SELECT * FROM prompt_amendments WHERE id = ?",
            (current_amendment_id,),
        ).fetchone()
        active = dict(row) if row else None
    elif not active:
        active = _get_active_amendment_row(conn)

    if not active:
        return []

    source_analysis = {}
    if active.get("source_analysis"):
        try:
            source_analysis = json.loads(active["source_analysis"])
        except (json.JSONDecodeError, TypeError):
            pass

    patterns = source_analysis.get("patterns_addressed", [])
    if not patterns:
        return []

    now = datetime.now(timezone.utc)
    results = []

    for error_type in patterns:
        # Find most recent correction of this type
        row = conn.execute(
            """SELECT MAX(created_at) as last_correction
               FROM correction_events
               WHERE error_type = ?""",
            (error_type,),
        ).fetchone()

        last_correction = row["last_correction"] if row and row["last_correction"] else None

        if last_correction:
            try:
                last_dt = datetime.fromisoformat(
                    last_correction.replace("Z", "+00:00")
                )
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days_since = int((now - last_dt).total_seconds() / 86400)
            except (ValueError, TypeError):
                days_since = 999
        else:
            days_since = 999  # never corrected

        if days_since >= 60:
            rule_status = "stale"
        elif days_since >= 30:
            rule_status = "possibly_stale"
        else:
            rule_status = "active"

        results.append({
            "error_type": error_type,
            "days_since_last_correction": days_since,
            "rule_status": rule_status,
        })

    return results


def _get_current_version_number(conn) -> int:
    """Return the highest existing amendment version number as int, or 0.

    Versions are stored as TEXT like 'v1', 'v2', etc.  We strip the 'v'
    prefix and parse the remaining digits.
    """
    row = conn.execute(
        "SELECT version FROM prompt_amendments ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row or not row["version"]:
        return 0
    ver_str = row["version"]
    # Strip leading 'v' if present
    digits = ver_str.lstrip("vV")
    try:
        return int(digits)
    except ValueError:
        return 0


def analyze_corrections_and_amend() -> str | None:
    """Analyse recent corrections and generate a new amendment if patterns exist.

    Uses EMA-weighted correction counts for generalization gating.
    Includes amendment effectiveness and staleness data in the prompt.

    Returns
    -------
    str | None
        The new amendment text, or None if insufficient corrections.
    """
    conn = get_connection()
    corrections = _get_unprocessed_corrections(conn)

    if not corrections:
        logger.info("No unprocessed corrections found.")
        return None

    result = _group_corrections(corrections)
    weighted_counts = result["weighted_counts"]
    groups = result["groups"]

    # Generalization gating: use weighted counts for threshold comparison
    actionable_groups: dict[str, list[dict]] = {}
    for k, raw_group in groups.items():
        threshold = _FAST_THRESHOLD if k in _FAST_TYPES else _SLOW_THRESHOLD
        weighted = weighted_counts.get(k, 0)
        if weighted >= threshold:
            actionable_groups[k] = raw_group

    if not actionable_groups:
        logger.info(
            "Found %d corrections across %d patterns, but none meet their "
            "generalization threshold (weighted). Fast types need %.1f, others need %.1f.",
            len(corrections), len(groups), _FAST_THRESHOLD, _SLOW_THRESHOLD,
        )
        return None

    # Compute amendment effectiveness (Feature 2)
    effectiveness_data = _compute_amendment_effectiveness(conn)

    # Detect stale rules (Feature 3)
    staleness_data = _detect_stale_rules(conn)

    # Get the current active amendment for context
    current_amendment = get_active_amendment() or "(No existing amendment)"
    current_version_num = _get_current_version_number(conn)
    new_version_num = current_version_num + 1
    new_version_str = f"v{new_version_num}"

    # Build the pattern summary for Claude
    pattern_descriptions: list[str] = []
    all_correction_ids: list[str] = []

    for correction_type, group_corrections in actionable_groups.items():
        all_correction_ids.extend(c["id"] for c in group_corrections)
        weighted = weighted_counts.get(correction_type, len(group_corrections))

        examples: list[str] = []
        for c in group_corrections[:5]:  # Show up to 5 examples per pattern
            orig = c.get("original_value", "")
            corrected = c.get("corrected_value", "")
            if isinstance(orig, str) and len(orig) > 200:
                orig = orig[:200] + "..."
            if isinstance(corrected, str) and len(corrected) > 200:
                corrected = corrected[:200] + "..."
            examples.append(
                f"    original: {orig}\n    corrected: {corrected}"
            )

        pattern_descriptions.append(
            f"Pattern: [{correction_type}] "
            f"({len(group_corrections)} raw corrections, "
            f"{weighted:.1f} weighted)\n"
            + "\n  ---\n".join(examples)
        )

    patterns_text = "\n\n".join(pattern_descriptions)

    # Build effectiveness section (Feature 2)
    effectiveness_text = ""
    if effectiveness_data:
        eff_lines = []
        for eff in effectiveness_data:
            status_note = ""
            if eff["effectiveness"] == "ineffective":
                status_note = " ⚠ This rule is NOT reducing errors. REVISE or REMOVE it."
            elif eff["effectiveness"] == "effective":
                status_note = " ✓ This rule is working. PRESERVE it."
            elif eff["effectiveness"] == "insufficient_data":
                status_note = " Not enough data to evaluate. PRESERVE for now."
            elif eff["effectiveness"] == "mixed":
                status_note = " Mixed results. Consider REVISING."
            eff_lines.append(
                f"  - {eff['error_type']}: {eff['corrections_before']} corrections before rule, "
                f"{eff['corrections_after']} after ({eff['period_days']}d). "
                f"{eff['effectiveness'].upper()}.{status_note}"
            )
        effectiveness_text = "\n\nEFFECTIVENESS OF CURRENT RULES:\n" + "\n".join(eff_lines)

    # Build staleness section (Feature 3)
    staleness_text = ""
    if staleness_data:
        stale_lines = []
        for s in staleness_data:
            status_note = ""
            if s["rule_status"] == "stale":
                status_note = (
                    " No corrections of this type in 60+ days. "
                    "Consider REMOVING this rule to reduce prompt size, "
                    "or CONSOLIDATING it with other rules."
                )
            elif s["rule_status"] == "possibly_stale":
                status_note = " No corrections in 30-60 days. Monitor."
            stale_lines.append(
                f"  - {s['error_type']}: Last correction {s['days_since_last_correction']}d ago. "
                f"{s['rule_status'].upper()}.{status_note}"
            )
        staleness_text = "\n\nRULE STALENESS:\n" + "\n".join(stale_lines)

    # Determine display threshold for prompt
    display_threshold = f"{_FAST_THRESHOLD}+ (fast types) or {_SLOW_THRESHOLD}+ (standard types) weighted occurrences"

    prompt = f"""You are maintaining a prompt amendment for an AI extraction system that
processes conversation transcripts. Users correct extraction errors, and you
synthesise those corrections into clear rules that prevent future mistakes.

IMPORTANT: Not every fix is a prompt fix. For each pattern, classify it into one of four buckets:
A. PROMPT FIX — Model misunderstands instructions. Tighten extraction rules/examples.
B. SCHEMA FIX — Data model is too crude. Suggest field or state additions.
C. THRESHOLD FIX — Logic is okay but trigger levels are off. Suggest rule changes.
D. UI/WORKFLOW FIX — Model may be okay but review is too hard. Suggest UI improvements.

For each pattern, state which bucket it falls into. Only write prompt amendments for bucket A.
For buckets B/C/D, describe the recommended fix but don't write prompt rules for them.

CURRENT AMENDMENT (v{current_version_num}):
{current_amendment}
{effectiveness_text}
{staleness_text}

NEW CORRECTION PATTERNS (each with {display_threshold}):
{patterns_text}

Generate an UPDATED amendment (v{new_version_num}) that:
1. Preserves all existing rules from the current amendment that are still valid
2. REMOVES or REVISES rules marked as INEFFECTIVE or STALE above
3. Adds new rules based on the correction patterns above
4. Uses clear, imperative language (e.g., "Treat X as Y", "Do not classify Z as...")
5. Includes specific examples where helpful
6. Groups related rules under clear headings

Format: plain text with section headers. Keep each rule concise (1-2 sentences).
Do NOT include any preamble — start directly with the amendment text.

The amendment will be prepended to extraction prompts, so write it as
direct instructions to the extraction model."""

    client = _get_client()
    response = client.messages.create(
        model=_AMENDMENT_MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    amendment_text = response.content[0].text.strip() if response.content else ""

    if not amendment_text:
        logger.error("Claude returned empty amendment text.")
        return None

    # Deactivate old amendments
    conn.execute("UPDATE prompt_amendments SET active = FALSE WHERE active = TRUE")

    # A3: Parse A/B/C/D bucket classifications from amendment output
    bucket_classifications = {}
    for line in amendment_text.split("\n"):
        line_stripped = line.strip()
        for bucket in ["A", "B", "C", "D"]:
            # Match patterns like "Bucket A:", "[A]", "A. PROMPT FIX", "A:"
            if (line_stripped.startswith(f"Bucket {bucket}:")
                    or line_stripped.startswith(f"[{bucket}]")
                    or line_stripped.startswith(f"{bucket}. ")
                    or line_stripped.startswith(f"{bucket}:")):
                # Extract the pattern name if present
                for pattern_key in actionable_groups:
                    if pattern_key.lower() in line_stripped.lower():
                        bucket_classifications[pattern_key] = bucket
                        break

    # Build source_analysis JSON that stores the correction_ids and
    # patterns_addressed (since those columns don't exist on the table).
    source_analysis_json = json.dumps({
        "correction_ids": all_correction_ids,
        "patterns_addressed": list(actionable_groups.keys()),
        "correction_count": len(all_correction_ids),
        "weighted_counts": {k: round(v, 2) for k, v in weighted_counts.items()
                           if k in actionable_groups},
        "effectiveness_snapshot": effectiveness_data,
        "staleness_snapshot": staleness_data,
        "bucket_classifications": bucket_classifications,
    })

    # Insert new amendment
    amendment_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO prompt_amendments
            (id, version, amendment_text, source_analysis,
             correction_count, active, created_at)
        VALUES (?, ?, ?, ?, ?, TRUE, ?)
        """,
        (
            amendment_id,
            new_version_str,
            amendment_text,
            source_analysis_json,
            len(all_correction_ids),
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    conn.commit()
    logger.info(
        "Generated amendment %s from %d corrections across %d patterns "
        "(EMA-weighted, effectiveness=%d rules tracked, stale=%d rules checked).",
        new_version_str,
        len(all_correction_ids),
        len(actionable_groups),
        len(effectiveness_data),
        len(staleness_data),
    )

    return amendment_text


# ---------------------------------------------------------------------------
# Contact-level extraction preferences
# ---------------------------------------------------------------------------


def get_contact_preferences(contact_id: str) -> dict | None:
    """Return the extraction preferences for a contact, or None."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT * FROM contact_extraction_preferences
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    return dict(row) if row else None


_ALLOWED_PREF_FIELDS = {
    "commitment_confidence_threshold", "typical_follow_through_rate",
    "extraction_depth", "vocal_alert_sensitivity",
    "relationship_importance", "custom_notes",
}


def update_contact_preference(
    contact_id: str, field: str, value: Any
) -> None:
    """Upsert a single preference field for a contact.

    Parameters
    ----------
    contact_id : str
        The unified_contacts.id.
    field : str
        The preference column to update (must be a valid column in
        contact_extraction_preferences).
    value : Any
        The new value (will be JSON-serialised if not a simple type).

    Raises
    ------
    ValueError
        If *field* is not in the allowed column whitelist.
    """
    if field not in _ALLOWED_PREF_FIELDS:
        raise ValueError(f"Invalid preference field: {field!r}")

    conn = get_connection()

    # Check if a row exists
    existing = conn.execute(
        "SELECT id FROM contact_extraction_preferences WHERE contact_id = ?",
        (contact_id,),
    ).fetchone()

    # Serialise complex values
    if isinstance(value, (dict, list)):
        value = json.dumps(value)

    now = datetime.now(timezone.utc).isoformat()

    if existing:
        conn.execute(
            f"""
            UPDATE contact_extraction_preferences
            SET {field} = ?, last_updated = ?
            WHERE contact_id = ?
            """,
            (value, now, contact_id),
        )
    else:
        pref_id = str(uuid.uuid4())
        conn.execute(
            f"""
            INSERT INTO contact_extraction_preferences
                (id, contact_id, {field}, last_updated, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pref_id, contact_id, value, now, now),
        )

    conn.commit()
    logger.info(
        "Updated preference %s=%s for contact %s", field, value, contact_id
    )


# ---------------------------------------------------------------------------
# Pass-specific amendment retrieval (A1)
# ---------------------------------------------------------------------------


def _get_amendment_for_pass(pass_name: str) -> str | None:
    """Return the active amendment text filtered by target_pass, or None.

    If the prompt_amendments table has a target_pass column, only return
    amendments matching the requested pass. Falls back gracefully if the
    column doesn't exist yet (pre-migration).
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT amendment_text FROM prompt_amendments
            WHERE active = TRUE AND target_pass = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (pass_name,),
        ).fetchone()
        return row["amendment_text"] if row else None
    except Exception:
        # Column doesn't exist yet — fall back to global
        return None


# ---------------------------------------------------------------------------
# Build extraction context (amendment + per-contact prefs)
# ---------------------------------------------------------------------------


def build_extraction_context(conversation_id: str, pass_name: str = "claims") -> str:
    """Build the amendment context string to prepend to extraction prompts.

    Combines:
    1. The active global amendment (learned patterns from all corrections)
    2. Per-contact preferences for any participants in the conversation

    Parameters
    ----------
    conversation_id : str
        The conversation being extracted.
    pass_name : str
        Which extraction pass is requesting context ("triage", "claims",
        "synthesis"). Used to filter amendments by target_pass when the
        column exists.

    Returns
    -------
    str
        Context string to prepend, or empty string if no amendments/prefs.
    """
    parts: list[str] = []

    # --- Global amendment ---
    # Try pass-specific amendment first, fall back to global
    amendment = _get_amendment_for_pass(pass_name) or get_active_amendment()
    if amendment:
        parts.append(
            "=== LEARNED EXTRACTION RULES ===\n"
            f"{amendment}\n"
            "=== END LEARNED RULES ==="
        )

    # --- Per-contact preferences ---
    conn = get_connection()

    # Find all contacts who participated in this conversation
    # transcripts uses speaker_id, not speaker_contact_id
    participants = conn.execute(
        """
        SELECT DISTINCT t.speaker_id
        FROM transcripts t
        WHERE t.conversation_id = ?
          AND t.speaker_id IS NOT NULL
        """,
        (conversation_id,),
    ).fetchall()

    contact_prefs_parts: list[str] = []
    for row in participants:
        cid = row["speaker_id"]
        prefs = get_contact_preferences(cid)
        if not prefs:
            continue

        # Get the contact name for readability
        # unified_contacts uses canonical_name, not display_name
        contact = conn.execute(
            "SELECT canonical_name FROM unified_contacts WHERE id = ?",
            (cid,),
        ).fetchone()
        name = (contact["canonical_name"] if contact else None) or cid

        # Build a human-readable preference block
        pref_lines: list[str] = []
        for key, val in prefs.items():
            if key in ("id", "contact_id", "created_at", "last_updated"):
                continue
            if val is None:
                continue
            # Try to de-serialise JSON strings for readability
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            pref_lines.append(f"  {key}: {val}")

        if pref_lines:
            contact_prefs_parts.append(
                f"Contact-specific rules for {name}:\n"
                + "\n".join(pref_lines)
            )

    if contact_prefs_parts:
        parts.append(
            "=== CONTACT-SPECIFIC PREFERENCES ===\n"
            + "\n\n".join(contact_prefs_parts) + "\n"
            "=== END CONTACT PREFERENCES ==="
        )

    return "\n\n".join(parts)
