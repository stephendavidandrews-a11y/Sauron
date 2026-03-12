"""Main routing orchestrator — dispatches extraction results to downstream apps.

Routes to:
- Networking App (localhost:3000) — interactions, commitments, contacts, signals
- CFTC Command Center (localhost:8000) — tasks, meetings, notes
- Sauron's own tables (graph edges stored in processor, not here)

UPDATED (v6): Handles three-pass extraction structure:
  {"triage": {...}, "claims": {...}, "synthesis": {...}}
  or flat dict for solo/triage-only results.
"""

import logging

from sauron.routing.networking import route_to_networking_app
from sauron.routing.cftc import route_to_cftc_app

logger = logging.getLogger(__name__)

CFTC_CONTEXTS = {"cftc_team", "cftc_stakeholder"}
NETWORKING_CONTEXTS = {"professional_network", "personal", "mixed"}


def route_extraction(conversation_id: str, extraction: dict):
    """Route extraction results to appropriate downstream systems.

    The extraction dict has one of three shapes:
    1. Three-pass result: {"triage": {...}, "claims": {...}, "synthesis": {...}}
    2. Solo result: flat SoloExtractionResult dict
    3. Triage-only: flat TriageResult dict (low-value, skipped deep extraction)
    """
    # Determine context classification
    if "triage" in extraction:
        # Three-pass result
        context = extraction["synthesis"].get("context_classification",
                    extraction["triage"].get("context_classification", "mixed"))
    else:
        # Flat result (solo or triage-only)
        context = extraction.get("context_classification", "mixed")

    # Triage-only — nothing to route (low-value conversation)
    if "value_assessment" in extraction and "summary" in extraction and "claims" not in extraction:
        logger.info(f"Triage-only result — no routing needed")
        return

    # Route to Networking App (almost everything goes here)
    try:
        net_ok = route_to_networking_app(conversation_id, extraction)
        if net_ok:
            logger.info(f"Networking routing succeeded for {conversation_id[:8]}")
        else:
            logger.warning(f"Networking routing returned failure for {conversation_id[:8]} (see routing_log)")
    except Exception:
        logger.exception("Networking app routing failed")

    # Route to CFTC if relevant context
    if context in CFTC_CONTEXTS or context == "mixed":
        try:
            route_to_cftc_app(conversation_id, extraction)
        except Exception:
            logger.exception("CFTC app routing failed")

    # Solo captures: route tasks to CFTC if they look like work items
    if context.startswith("solo_"):
        _route_solo(conversation_id, extraction)


def _route_solo(conversation_id: str, extraction: dict):
    """Route solo capture content based on content type.

    CFTC routing: tasks from solo captures.
    Networking routing: handled by route_to_networking_app() via solo
    normalization — debrief/prep solos have their fields mapped into
    synthesis-compatible shape so existing lanes pick them up naturally.
    """
    tasks = extraction.get("tasks", [])
    if tasks:
        try:
            route_to_cftc_app(conversation_id, extraction)
        except Exception:
            logger.exception("Solo CFTC routing failed")
