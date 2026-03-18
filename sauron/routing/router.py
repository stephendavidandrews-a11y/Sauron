"""Main routing orchestrator — dispatches extraction results to downstream apps.

Routes to:
- Networking App (localhost:3000) — interactions, commitments, contacts, signals
- Sauron's own tables (graph edges stored in processor, not here)

UPDATED (v6): Handles three-pass extraction structure:
  {"triage": {...}, "claims": {...}, "synthesis": {...}}
  or flat dict for solo/triage-only results.
"""

import logging

from sauron.routing.networking import route_to_networking_app

logger = logging.getLogger(__name__)

NETWORKING_CONTEXTS = {"professional_network", "personal", "mixed",
                       "cftc_team", "cftc_stakeholder"}


def route_extraction(conversation_id: str, extraction: dict):
    """Route extraction results to appropriate downstream systems.

    The extraction dict has one of three shapes:
    1. Three-pass result: {"triage": {...}, "claims": {...}, "synthesis": {...}}
    2. Solo result: flat SoloExtractionResult dict
    3. Triage-only: flat TriageResult dict (low-value, skipped deep extraction)
    """
    # Determine context classification
    if "triage" in extraction:
        context = extraction["synthesis"].get("context_classification",
                    extraction["triage"].get("context_classification", "mixed"))
    else:
        context = extraction.get("context_classification", "mixed")

    # Triage-only — nothing to route (low-value conversation)
    if "value_assessment" in extraction and "summary" in extraction and "claims" not in extraction:
        logger.info(f"Triage-only result — no routing needed")
        return

    # Route to Networking App (all contexts)
    try:
        net_ok = route_to_networking_app(conversation_id, extraction)
        if net_ok:
            logger.info(f"Networking routing succeeded for {conversation_id[:8]}")
        else:
            logger.warning(f"Networking routing returned failure for {conversation_id[:8]} (see routing_log)")
    except Exception:
        logger.exception("Networking app routing failed")
