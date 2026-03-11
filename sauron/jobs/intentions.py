"""
sauron/jobs/intentions.py

Meeting intentions — the prep -> conversation -> debrief feedback loop.

Allows creating pre-meeting goals and strategies, auto-linking them to
conversations when they happen, assessing goal achievement against the
deep extraction, and generating pre-meeting game plans from historical data.

FIXED: Column names aligned to actual DB schema:
  - meeting_intentions has no linked_at or debrief_linked_at columns
  - unified_contacts uses canonical_name, not display_name
  - conversations has no title column -> use manual_note or id
  - transcripts uses speaker_id, not speaker_contact_id
  - graph_edges uses from_entity/to_entity/strength, not source_contact_id/target_contact_id/weight
  - vocal_features stores actual feature values per row, not feature_name/value pairs
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import anthropic

from sauron.config import TRIAGE_MODEL
from sauron.db.connection import get_connection

logger = logging.getLogger(__name__)

# Use Haiku for fast, cheap intention assessments
_HAIKU_MODEL = TRIAGE_MODEL
_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    """Lazy-init the Anthropic client (reads ANTHROPIC_API_KEY from env)."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# ---------------------------------------------------------------------------
# Create / link intentions
# ---------------------------------------------------------------------------


def create_intention(
    goals: list[str],
    concerns: list[str] | None = None,
    strategy: str | None = None,
    target_contact_id: str | None = None,
) -> str:
    """Create a new meeting intention record.

    Parameters
    ----------
    goals : list[str]
        What you want to accomplish in the meeting.
    concerns : list[str] | None
        Things to watch out for or be careful about.
    strategy : str | None
        Overall approach / talking points.
    target_contact_id : str | None
        Primary contact the meeting is with.

    Returns
    -------
    str
        The new intention ID.
    """
    conn = get_connection()
    intention_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # Generate the auto brief if we have a contact
    auto_brief = None
    if target_contact_id:
        try:
            auto_brief = generate_auto_brief(target_contact_id, goals)
        except Exception as exc:
            logger.warning("Auto-brief generation failed: %s", exc)

    conn.execute(
        """
        INSERT INTO meeting_intentions
            (id, goals, concerns, strategy, target_contact_id,
             auto_brief, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            intention_id,
            json.dumps(goals),
            json.dumps(concerns) if concerns else None,
            strategy,
            target_contact_id,
            auto_brief,
            now,
        ),
    )
    conn.commit()
    logger.info("Created intention %s with %d goals", intention_id, len(goals))
    return intention_id


def link_intention_to_conversation(
    intention_id: str, conversation_id: str
) -> None:
    """Link a prep intention to the actual conversation that took place.

    The meeting_intentions table has no linked_at column; we simply set
    conversation_id.
    """
    conn = get_connection()
    conn.execute(
        """
        UPDATE meeting_intentions
        SET conversation_id = ?
        WHERE id = ?
        """,
        (conversation_id, intention_id),
    )
    conn.commit()
    logger.info(
        "Linked intention %s to conversation %s", intention_id, conversation_id
    )


def link_debrief(intention_id: str, debrief_conversation_id: str) -> None:
    """Link a debrief capture to an existing intention.

    The meeting_intentions table has no debrief_linked_at column; we simply
    set debrief_conversation_id.
    """
    conn = get_connection()
    conn.execute(
        """
        UPDATE meeting_intentions
        SET debrief_conversation_id = ?
        WHERE id = ?
        """,
        (debrief_conversation_id, intention_id),
    )
    conn.commit()
    logger.info(
        "Linked debrief %s to intention %s",
        debrief_conversation_id,
        intention_id,
    )


# ---------------------------------------------------------------------------
# Find unlinked intentions (for auto-linking)
# ---------------------------------------------------------------------------


def find_unlinked_intention(
    contact_id: str, time_window_hours: int = 4
) -> str | None:
    """Find the most recent intention for a contact that hasn't been linked.

    Used by the pipeline to auto-link when a conversation is processed
    and we detect the target contact participated.

    Parameters
    ----------
    contact_id : str
        The unified_contacts.id of the person.
    time_window_hours : int
        Only consider intentions created within this many hours.

    Returns
    -------
    str | None
        The intention ID, or None if nothing matches.
    """
    conn = get_connection()
    cutoff = (
        datetime.utcnow() - timedelta(hours=time_window_hours)
    ).isoformat()

    row = conn.execute(
        """
        SELECT id FROM meeting_intentions
        WHERE target_contact_id = ?
          AND conversation_id IS NULL
          AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (contact_id, cutoff),
    ).fetchone()

    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Goal assessment
# ---------------------------------------------------------------------------


def assess_goals(intention_id: str, extraction: dict) -> dict:
    """Assess how well the stated goals were achieved in the conversation.

    Uses Claude Haiku to compare the pre-meeting goals against the deep
    extraction output and produce an achievement assessment.

    Parameters
    ----------
    intention_id : str
        The meeting intention to assess.
    extraction : dict
        The deep extraction result (parsed extraction_json).

    Returns
    -------
    dict
        Assessment with per-goal status and evidence.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM meeting_intentions WHERE id = ?",
        (intention_id,),
    ).fetchone()

    if not row:
        raise ValueError(f"Intention {intention_id} not found")

    goals = json.loads(row["goals"]) if row["goals"] else []
    concerns = json.loads(row["concerns"]) if row["concerns"] else []
    strategy = row["strategy"] or ""

    if not goals:
        return {"assessments": [], "overall": "no_goals_defined"}

    # Build the prompt
    goals_text = "\n".join(f"  {i + 1}. {g}" for i, g in enumerate(goals))
    concerns_text = (
        "\n".join(f"  - {c}" for c in concerns) if concerns else "None stated."
    )

    prompt = f"""You are assessing how well pre-meeting goals were achieved based on
the actual conversation extraction.

PRE-MEETING GOALS:
{goals_text}

PRE-MEETING CONCERNS:
{concerns_text}

PRE-MEETING STRATEGY:
{strategy or 'None stated.'}

CONVERSATION EXTRACTION:
{json.dumps(extraction, indent=2, default=str)[:8000]}

For each goal, respond with a JSON object:
{{
  "assessments": [
    {{
      "goal": "<the goal text>",
      "status": "achieved" | "partial" | "not_achieved",
      "confidence": 0.0-1.0,
      "evidence": "<specific evidence from the extraction>",
      "notes": "<any additional context>"
    }}
  ],
  "overall_assessment": "<1-2 sentence summary>",
  "unexpected_outcomes": ["<anything significant that happened outside the goals>"],
  "suggestions_for_next_time": ["<brief tactical suggestions>"]
}}

Respond with ONLY the JSON object, no other text."""

    client = _get_client()
    response = client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        result_text = response.content[0].text.strip()
        # Handle possible markdown code fences
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
        assessment = json.loads(result_text)
    except (json.JSONDecodeError, IndexError) as exc:
        logger.error("Failed to parse goal assessment: %s", exc)
        assessment = {
            "assessments": [],
            "overall_assessment": "Assessment parsing failed",
            "raw_response": response.content[0].text if response.content else "",
        }

    # Persist the assessment — also store unexpected_outcomes and outcome_notes
    unexpected = assessment.get("unexpected_outcomes", [])
    overall = assessment.get("overall_assessment", "")
    conn.execute(
        """
        UPDATE meeting_intentions
        SET goals_achieved = ?,
            outcome_notes = ?,
            unexpected_outcomes = ?,
            assessed_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(assessment),
            overall,
            json.dumps(unexpected) if unexpected else None,
            datetime.utcnow().isoformat(),
            intention_id,
        ),
    )
    conn.commit()
    logger.info("Goal assessment completed for intention %s", intention_id)

    return assessment


# ---------------------------------------------------------------------------
# Auto-brief generation
# ---------------------------------------------------------------------------


def generate_auto_brief(contact_id: str, goals: list[str]) -> str:
    """Generate a pre-meeting game plan for a contact.

    Pulls recent conversations, vocal baselines, open commitments, and
    graph edges to build context, then uses Claude Haiku to produce a
    concise, actionable brief.

    Parameters
    ----------
    contact_id : str
        The unified_contacts.id.
    goals : list[str]
        What you want to achieve in the upcoming meeting.

    Returns
    -------
    str
        Markdown-formatted game plan.
    """
    conn = get_connection()

    # --- Contact info ---
    # unified_contacts uses canonical_name, not display_name
    contact = conn.execute(
        "SELECT * FROM unified_contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    contact_name = (
        (contact["canonical_name"] if contact else None) or contact_id
    )

    # --- Recent conversations ---
    # conversations has no title column; use manual_note or id
    # transcripts uses speaker_id, not speaker_contact_id
    recent_convos = conn.execute(
        """
        SELECT DISTINCT c.id, c.manual_note, c.created_at, c.duration_seconds
        FROM conversations c
        JOIN transcripts t ON t.conversation_id = c.id
        WHERE t.speaker_id = ?
        ORDER BY c.created_at DESC
        LIMIT 5
        """,
        (contact_id,),
    ).fetchall()

    conversation_context: list[str] = []
    for conv in recent_convos:
        ext = conn.execute(
            """
            SELECT extraction_json FROM extractions
            WHERE conversation_id = ?
            ORDER BY pass_number DESC LIMIT 1
            """,
            (conv["id"],),
        ).fetchone()
        summary = ""
        if ext:
            try:
                data = json.loads(ext["extraction_json"])
                summary = data.get("summary") or data.get("conversation_summary") or ""
            except (json.JSONDecodeError, TypeError):
                pass
        date_str = conv["created_at"][:10] if conv["created_at"] else "unknown"
        label = conv["manual_note"] or conv["id"][:8]
        conversation_context.append(
            f"- {date_str}: {label} — {summary[:200]}"
        )

    # --- Open commitments ---
    commitments: list[str] = []
    for conv in recent_convos:
        ext = conn.execute(
            """
            SELECT extraction_json FROM extractions
            WHERE conversation_id = ?
            ORDER BY pass_number DESC LIMIT 1
            """,
            (conv["id"],),
        ).fetchone()
        if not ext:
            continue
        try:
            data = json.loads(ext["extraction_json"])
            for key in ("my_commitments", "contact_commitments", "follow_ups"):
                for item in data.get(key, []):
                    txt = item if isinstance(item, str) else (
                        item.get("description") or item.get("text") or ""
                    )
                    if txt:
                        commitments.append(txt)
        except (json.JSONDecodeError, TypeError):
            pass

    # --- Vocal baselines ---
    # vocal_features stores actual column values (pitch_mean, jitter, etc.)
    # per row, not feature_name/value pairs.  Use vocal_baselines table for
    # the aggregate baseline per contact.
    vocal_info = ""
    baseline = conn.execute(
        """
        SELECT pitch_mean, pitch_std, jitter, shimmer, hnr,
               speaking_rate_wpm, spectral_centroid
        FROM vocal_baselines
        WHERE contact_id = ?
        LIMIT 1
        """,
        (contact_id,),
    ).fetchone()
    if baseline:
        parts = []
        for col in ("pitch_mean", "pitch_std", "jitter", "shimmer", "hnr",
                     "speaking_rate_wpm", "spectral_centroid"):
            val = baseline[col]
            if val is not None:
                parts.append(f"{col}={val:.2f}")
        if parts:
            vocal_info = "Vocal baseline: " + ", ".join(parts)

    # --- Graph edges (relationship context) ---
    # graph_edges uses from_entity/to_entity/strength, not
    # source_contact_id/target_contact_id/weight
    edges = conn.execute(
        """
        SELECT to_entity, edge_type, strength, observed_at
        FROM graph_edges
        WHERE from_entity = ? AND from_type = 'contact'
        ORDER BY strength DESC
        LIMIT 5
        """,
        (contact_id,),
    ).fetchall()
    relationship_context = ""
    if edges:
        edge_strs = []
        for e in edges:
            target = conn.execute(
                "SELECT canonical_name FROM unified_contacts WHERE id = ?",
                (e["to_entity"],),
            ).fetchone()
            tname = target["canonical_name"] if target else e["to_entity"]
            strength = e["strength"] or 0
            edge_strs.append(
                f"{tname} ({e['edge_type']}, strength={strength:.2f})"
            )
        relationship_context = "Network connections: " + "; ".join(edge_strs)

    # --- Generate brief with Claude ---
    goals_text = "\n".join(f"  {i + 1}. {g}" for i, g in enumerate(goals))

    prompt = f"""Generate a concise pre-meeting game plan for a meeting with {contact_name}.

MY GOALS:
{goals_text}

RECENT CONVERSATION HISTORY:
{chr(10).join(conversation_context) if conversation_context else 'No prior conversations on record.'}

OPEN COMMITMENTS/FOLLOW-UPS:
{chr(10).join(f'- {c}' for c in commitments[:10]) if commitments else 'None tracked.'}

{vocal_info}

{relationship_context}

Write a brief, actionable game plan in markdown format. Include:
1. Key context to remember (max 3 bullets)
2. Specific talking points aligned to goals (max 5)
3. Open items to address (commitments, follow-ups)
4. Tactical notes (communication style observations if available)

Keep it under 300 words. Be direct and useful."""

    client = _get_client()
    response = client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    brief = response.content[0].text.strip() if response.content else ""
    logger.info("Generated auto-brief for contact %s (%d chars)", contact_id, len(brief))
    return brief
