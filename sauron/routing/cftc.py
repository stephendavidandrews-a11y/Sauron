"""Route extraction results to the CFTC Command Center (localhost:8000).

Handles v6 three-pass structure {"triage", "claims", "synthesis"}
and flat solo extraction results.

Routing rules:
- Personal/professional commitments → Networking App (not here)
- Work assignments → CFTC Task
- Stakeholder meetings → CFTC meeting record
- Team vocal observations → CFTC manager note
"""

import logging

import httpx

from sauron.config import CFTC_APP_URL

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=5.0)


def route_to_cftc_app(conversation_id: str, extraction: dict):
    """Route CFTC-relevant extraction data to the Command Center."""
    # Unpack v6 three-pass result
    if "synthesis" in extraction:
        synthesis = extraction["synthesis"]
        triage = extraction.get("triage", {})
    else:
        synthesis = extraction
        triage = extraction

    context = synthesis.get("context_classification",
                triage.get("context_classification", ""))

    # Work commitments → tasks (only those assigned to team members)
    for c in synthesis.get("my_commitments", []):
        if _is_work_task(c, context):
            _create_task(conversation_id, c)
    for c in synthesis.get("contact_commitments", []):
        if _is_work_task(c, context):
            _create_task(conversation_id, c)

    # Solo tasks
    for task_desc in synthesis.get("tasks", []):
        _create_task(conversation_id, {"description": task_desc})

    # Stakeholder meeting record
    if context == "cftc_stakeholder":
        _create_meeting(conversation_id, synthesis)

    # Manager notes from team conversations (vocal observations)
    if context == "cftc_team":
        _create_note(conversation_id, synthesis)

    # Policy positions → could feed into CFTC pipeline intelligence
    for pp in synthesis.get("policy_positions", []):
        _create_policy_signal(conversation_id, pp, context)


def _is_work_task(commitment: dict, context: str) -> bool:
    """Determine if a commitment is a work task (CFTC) vs personal commitment."""
    if context in ("cftc_team", "cftc_stakeholder"):
        return True
    # Mixed context: check for work indicators
    desc = commitment.get("description", "").lower()
    work_signals = ("draft", "memo", "report", "review", "analysis",
                    "regulation", "rule", "enforcement", "compliance",
                    "deadline", "brief", "filing", "comment")
    return any(w in desc for w in work_signals)


def _create_task(conversation_id: str, commitment: dict):
    """Create a Task in the CFTC work management system."""
    try:
        payload = {
            "title": commitment.get("description", ""),
            "source_system": "sauron",
            "source_id": conversation_id,
            "status": "not_started",
            "assignee_name": commitment.get("assignee"),
            "due_date": commitment.get("resolved_date"),
            "priority_label": _infer_priority(commitment),
        }
        resp = httpx.post(
            f"{CFTC_APP_URL}/api/v1/pipeline/work/tasks",
            json=payload,
            timeout=TIMEOUT,
        )
        if resp.status_code < 300:
            logger.info(f"Created CFTC task: {commitment.get('description', '')[:60]}")
        else:
            logger.warning(f"CFTC task creation returned {resp.status_code}")
    except httpx.ConnectError:
        logger.warning("CFTC app not reachable — skipping task creation")
    except Exception:
        logger.exception("Failed to create CFTC task")


def _create_meeting(conversation_id: str, synthesis: dict):
    """Create a stakeholder meeting record."""
    try:
        payload = {
            "type": "meeting",
            "title": f"Conversation: {synthesis.get('summary', '')[:100]}",
            "summary": synthesis.get("summary", ""),
            "topics": synthesis.get("topics_discussed", []),
            "source_system": "sauron",
            "source_id": conversation_id,
        }
        resp = httpx.post(
            f"{CFTC_APP_URL}/api/v1/pipeline/stakeholders/meetings",
            json=payload,
            timeout=TIMEOUT,
        )
        if resp.status_code < 300:
            logger.info("Created CFTC stakeholder meeting")
    except httpx.ConnectError:
        logger.warning("CFTC app not reachable — skipping")
    except Exception:
        logger.exception("Failed to create CFTC meeting")


def _create_note(conversation_id: str, synthesis: dict):
    """Create a manager note from team conversation with vocal insights."""
    coaching = []  # self_coaching removed
    vocal_summary = synthesis.get("vocal_intelligence_summary")
    alignment = synthesis.get("word_voice_alignment", "neutral")

    if not coaching and not vocal_summary:
        return

    try:
        content_parts = []
        if vocal_summary:
            content_parts.append(f"Vocal observation: {vocal_summary}")
        if alignment == "misaligned":
            content_parts.append("⚠️ Word-voice misalignment detected")
        for item in coaching:
            obs = item.get("observation", "")
            rec = item.get("recommendation", "")
            content_parts.append(f"- {obs}" + (f" → {rec}" if rec else ""))

        payload = {
            "note_type": "sauron_observation",
            "content": "\n".join(content_parts),
            "context_type": "team_conversation",
            "source_system": "sauron",
            "source_id": conversation_id,
        }
        httpx.post(
            f"{CFTC_APP_URL}/api/v1/pipeline/work/notes",
            json=payload,
            timeout=TIMEOUT,
        )
    except httpx.ConnectError:
        logger.warning("CFTC app not reachable — skipping")
    except Exception:
        logger.exception("Failed to create CFTC note")


def _create_policy_signal(conversation_id: str, position: dict, context: str):
    """Route policy position intelligence to CFTC pipeline."""
    if context not in ("cftc_team", "cftc_stakeholder", "mixed"):
        return

    try:
        payload = {
            "signal_type": "policy_position",
            "person": position.get("person", ""),
            "topic": position.get("topic", ""),
            "position": position.get("position", ""),
            "strength": position.get("strength", 0.5),
            "notes": position.get("notes", ""),
            "source_system": "sauron",
            "source_id": conversation_id,
        }
        httpx.post(
            f"{CFTC_APP_URL}/api/v1/pipeline/interagency-rules",
            json=payload,
            timeout=TIMEOUT,
        )
    except httpx.ConnectError:
        logger.warning("CFTC app not reachable — skipping")
    except Exception:
        logger.exception("Failed to create policy signal")


def _infer_priority(commitment: dict) -> str:
    """Infer task priority from commitment data."""
    confidence = commitment.get("confidence", 0.5)
    desc = commitment.get("description", "").lower()

    if confidence >= 0.9 or any(w in desc for w in ("urgent", "asap", "immediately")):
        return "high"
    if confidence >= 0.7:
        return "medium"
    return "low"
