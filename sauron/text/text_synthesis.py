"""Lightweight text synthesis — pass 3 for routing fields.

The voice pipeline runs Opus for synthesis (graph_edges, follow_ups,
standing_offers, etc.). For text, we run a focused Sonnet call to produce
the same routing-critical fields at lower cost (~$0.02 per cluster).

This runs AFTER claims extraction (pass 2) and produces the synthesis
payload that reviewed_payload.py loads as pass 3 for routing.
"""

import json
import logging

import anthropic

from sauron.config import CLAIMS_MODEL
from sauron.extraction.json_utils import extract_json

logger = logging.getLogger(__name__)

TEXT_SYNTHESIS_SYSTEM_PROMPT = """You are a synthesis module for a personal text intelligence platform owned by Stephen Andrews.
You receive a text conversation along with already-extracted claims. Your job is to produce
ROUTING-CRITICAL synthesis fields that the claims pass doesn't cover.

Output valid JSON with these fields:

{
  "summary": "1-2 sentence summary of the conversation",
  "relationship_notes": "Brief note on relationship dynamics observed, or null",
  "graph_edges": [
    {
      "from_entity": "Full Name",
      "from_type": "person",
      "to_entity": "Full Name",
      "to_type": "person | organization",
      "edge_type": "knows | works_with | reports_to | manages | advises | family | friend | works_at | lobbies | represents | collaborates_with",
      "strength": 0.0-1.0
    }
  ],
  "follow_ups": [
    {
      "description": "What needs to happen next",
      "owner": "Full Name of person responsible",
      "urgency": "high | medium | low",
      "related_claim_id": "claim_xxx or null"
    }
  ],
  "topics_discussed": ["topic1", "topic2"],
  "standing_offers": [],
  "policy_positions": [],
  "referenced_resources": [],
  "calendar_events": [],
  "life_events": [],
  "context_classification": "professional_network | personal | mixed | cftc_team | cftc_stakeholder"
}

GRAPH EDGES RULES:
- Extract ALL relationship connections mentioned or demonstrated in the conversation
- Include connections between ANY people mentioned, not just participants
  e.g., "Schmitt's staffer Ethan" → edge from Senator Schmitt to Ethan (works_for)
- Include person-to-organization connections
  e.g., "Sarah works at Treasury" → edge from Sarah to Treasury (works_at)
- Strength: 0.9+ for established/stated relationships, 0.5-0.8 for mentioned/contextual
- edge_type should be specific: prefer "works_with" over "knows" when evidence supports it
- Include Stephen Andrews in edges when he has demonstrated relationships with participants
- DO NOT create self-referential edges (same person on both sides)

*** CRITICAL — NAME CONSISTENCY ***
Use the EXACT same person names as in the claims JSON above. If the claims
use "Ethan Harper", use "Ethan Harper" in graph edges — NOT "Ethan". If the
claims use "Chuck Grassley", use "Chuck Grassley" — NOT "Senator Grassley".
The claims JSON is the canonical name source. Match it exactly.

FOLLOW-UPS:
- Extract next-step items that aren't captured as commitment claims
- These are more like "the ball is in motion" observations
- Only include if there's clear next action needed

STANDING_OFFERS, POLICY_POSITIONS, REFERENCED_RESOURCES, CALENDAR_EVENTS, LIFE_EVENTS:
- Include only if clearly present in the conversation
- Empty arrays are fine and expected for most text clusters

CONTEXT_CLASSIFICATION — choose the most accurate:
- professional_network: Business, career, professional relationships
- personal: Family, friends, personal matters
- mixed: Both professional and personal elements
- cftc_team: CFTC internal team discussion
- cftc_stakeholder: CFTC external stakeholder communication
"""


def synthesize_text_cluster(
    transcript: str,
    claims_json: str,
    participant_roster: str,
    metadata: dict,
    triage: dict,
) -> tuple[dict, dict]:
    """Run lightweight Sonnet synthesis on a text cluster.

    Args:
        transcript: Formatted text from preprocessor
        claims_json: JSON string of extracted claims (from pass 2)
        participant_roster: From build_text_participant_roster()
        metadata: Cluster metadata
        triage: Triage result

    Returns:
        (synthesis_dict, usage_dict)
    """
    client = anthropic.Anthropic()

    parts = []

    if participant_roster:
        parts.append(participant_roster)

    parts.append(f"## Triage Summary\n{triage.get('summary', 'No summary')}")

    parts.append(f"## Already Extracted Claims\n{claims_json}")

    parts.append(f"---\n\n## Text Conversation\n\n{transcript}")

    user_content = "\n\n".join(parts)

    logger.info(
        "Running text synthesis for cluster %s...",
        metadata.get("cluster_id", "?"),
    )

    response = client.messages.create(
        model=CLAIMS_MODEL,
        max_tokens=4096,
        system=TEXT_SYNTHESIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw_text = response.content[0].text.strip()
    json_text = extract_json(raw_text)
    result = json.loads(json_text)

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    edge_count = len(result.get("graph_edges", []))
    followup_count = len(result.get("follow_ups", []))

    logger.info(
        "Text synthesis complete: %d graph_edges, %d follow_ups | %d in / %d out tokens",
        edge_count, followup_count,
        usage["input_tokens"], usage["output_tokens"],
    )

    return result, usage
