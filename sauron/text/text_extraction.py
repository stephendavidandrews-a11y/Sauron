"""Text-specific extraction — triage + claims for text clusters.

Parallels the voice extraction pipeline (triage.py + claims.py) but with
prompts tuned for text message characteristics:
- No timestamps (line numbers instead)
- No vocal analysis (no audio)
- Evidence quality field (explicit/abbreviated/ambiguous/inferred)
- Conservative inference (text is more ambiguous than voice)
- Reaction/attachment awareness

Reuses the same Pydantic schemas (Claim, ClaimsResult) from extraction/schemas.py
with the addition of evidence_quality on each claim.

Cost per cluster:
- Triage (Haiku): ~$0.005
- Claims (Sonnet): ~$0.02
- Total Lane 2: ~$0.025
"""

import hashlib
import json
import logging

import anthropic

from sauron.config import TRIAGE_MODEL, CLAIMS_MODEL
from sauron.extraction.json_utils import extract_json
from sauron.extraction.claims_base import build_text_claims_prompt
from sauron.learning.amendments import build_extraction_context
from sauron.extraction.schemas import ClaimsResult

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# TEXT TRIAGE (Haiku) — assigns depth lane
# ═══════════════════════════════════════════════════════════════

TEXT_TRIAGE_SYSTEM_PROMPT = """You are a text message triage system for a personal intelligence platform owned by Stephen Andrews.
You receive a formatted text conversation cluster and must classify it for processing depth.

Output valid JSON matching this schema exactly:
{
  "modality": "text",
  "depth_lane": 0 | 1 | 2 | 3,
  "depth_rationale": "brief explanation of lane assignment",
  "cluster_classification": "logistical_only | low_substance | substantive_explicit | synthesis_worthy",
  "context_classification": "professional_network | personal | mixed | cftc_team | cftc_stakeholder",
  "value_assessment": "high | medium | low | none",
  "summary": "2-3 sentence summary of the conversation",
  "topic_tags": ["topic1", "topic2"],
  "has_actionable_content": true | false
}

DEPTH LANE ASSIGNMENT:

Lane 0 (thin capture): Pure logistics, single-emoji exchanges, confirmations with no
  actionable content. "ok", "👍", "see you at 3", time/place coordination only.
  Classification: logistical_only OR low_substance with no actionable content.

Lane 1 (Haiku label only): Low-substance but useful for context — scheduling
  confirmations, brief check-ins, social pleasantries with a fact or two.
  Available for search and Today dashboard but no claims extracted.
  Classification: low_substance with scheduling/confirmations.

Lane 2 (Haiku → Sonnet): Default substantive lane. Most worthwhile text — explicit
  facts, asks, commitments, decisions, follow-ups, position statements, relationship
  signals. This is the workhorse lane.
  Classification: substantive_explicit.

Lane 3 (Haiku → Sonnet → Opus): Reserved for clusters whose value depends on
  higher-order synthesis. Detected position shifts, multi-perspective strategy
  discussions, contradictions requiring integration, multi-step negotiations.
  This is RARE for text.
  Classification: synthesis_worthy.

RULES:
- Short exchanges with clear commitments ("I'll send it by Friday") → Lane 2, not Lane 0/1
- "sounds good" / "ok" / emoji-only → Lane 0
- Brief check-in with one factual update → Lane 1
- Most real conversations with substance → Lane 2
- Lane 3 is RARE: only when synthesis adds value beyond extraction
"""


def triage_text_cluster(
    transcript: str,
    metadata: dict,
) -> dict:
    """Run Haiku triage on a text cluster to assign depth lane.

    Args:
        transcript: Formatted text from preprocessor
        metadata: Cluster metadata (thread_type, participant_count, etc.)

    Returns:
        dict with triage fields (depth_lane, summary, classification, etc.)
    """
    client = anthropic.Anthropic(max_retries=2)

    context_header = (
        f"Thread type: {metadata.get('thread_type', 'unknown')}\n"
        f"Participants: {metadata.get('participant_count', 'unknown')}\n"
        f"Display name: {metadata.get('display_name', 'unknown')}\n"
    )

    logger.info(
        "Running text triage for cluster %s (%d messages)...",
        metadata.get("cluster_id", "?"),
        metadata.get("message_count", 0),
    )

    response = client.messages.create(
        model=TRIAGE_MODEL,
        max_tokens=1024,
        system=TEXT_TRIAGE_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"{context_header}\n"
                f"Triage this text conversation cluster:\n\n{transcript}"
            ),
        }],
    )

    raw_text = response.content[0].text.strip()
    json_text = extract_json(raw_text)
    result = json.loads(json_text)

    # Enforce group chat bias: one lane lower, but NOT for high-value clusters
    # High-value group chats with substantive content deserve full extraction
    if (metadata.get("thread_type") == "group"
            and result.get("depth_lane", 0) > 0
            and result.get("value_assessment") != "high"):
        original = result["depth_lane"]
        result["depth_lane"] = max(0, original - 1)
        if original != result["depth_lane"]:
            result["depth_rationale"] = (
                f"{result.get('depth_rationale', '')} "
                f"[Group chat bias: {original} → {result['depth_lane']}]"
            )
    elif metadata.get("thread_type") == "group" and result.get("value_assessment") == "high":
        result["depth_rationale"] = (
            f"{result.get('depth_rationale', '')} "
            f"[Group chat bias skipped: high value]"
        )

    logger.info(
        "Text triage: lane=%d, classification=%s, value=%s, summary=%s",
        result.get("depth_lane", -1),
        result.get("cluster_classification", "?"),
        result.get("value_assessment", "?"),
        (result.get("summary", "")[:80] + "...") if len(result.get("summary", "")) > 80 else result.get("summary", ""),
    )

    return result, response.usage


# ═══════════════════════════════════════════════════════════════
# TEXT CLAIMS EXTRACTION (Sonnet) — Lane 2+
# ═══════════════════════════════════════════════════════════════

TEXT_CLAIMS_SYSTEM_PROMPT = build_text_claims_prompt()


def extract_text_claims(
    transcript: str,
    participant_roster: str,
    metadata: dict,
    triage: dict,
    conversation_id: str = "",
) -> tuple[ClaimsResult, dict]:
    """Run Sonnet claims extraction on a text cluster.

    Unlike voice, text clusters are small enough to process in a single
    API call (no episode batching needed). A typical cluster is 5-50
    messages / 200-5000 chars.

    Args:
        transcript: Formatted text from preprocessor
        participant_roster: From build_text_participant_roster()
        metadata: Cluster metadata
        triage: Triage result (for context)
        conversation_id: For content-deterministic claim IDs

    Returns:
        (ClaimsResult, usage_dict)
    """
    client = anthropic.Anthropic(max_retries=2)

    # Build user content
    parts = []

    if participant_roster:
        parts.append(participant_roster)

    # Add triage context
    triage_summary = triage.get("summary", "")
    topic_tags = triage.get("topic_tags", [])
    if triage_summary or topic_tags:
        context = f"## Triage Summary\n{triage_summary}"
        if topic_tags:
            context += f"\nTopics: {', '.join(topic_tags)}"
        parts.append(context)

    # Thread metadata — include cluster date for commitment date resolution
    cluster_date = ""
    start_time = metadata.get("start_time", "")
    if start_time:
        try:
            from datetime import datetime as _dt
            from zoneinfo import ZoneInfo as _ZI
            _ts = _dt.fromisoformat(start_time.replace("Z", "+00:00"))
            _local = _ts.astimezone(_ZI("America/New_York"))
            cluster_date = _local.strftime("%A, %Y-%m-%d")  # e.g., "Thursday, 2026-03-13"
        except Exception:
            cluster_date = start_time[:10]

    thread_info = (
        f"## Thread Info\n"
        f"Type: {metadata.get('thread_type', 'unknown')}\n"
        f"Display name: {metadata.get('display_name', 'unknown')}\n"
        f"Messages: {metadata.get('message_count', '?')}"
    )
    if cluster_date:
        thread_info += f"\nCluster date: {cluster_date} (use for resolving relative dates in commitments)"
    parts.append(thread_info)

    parts.append(f"---\n\n## Text Conversation\n\n{transcript}")

    user_content = "\n\n".join(parts)

    logger.info(
        "Running text claims extraction for cluster %s (%d messages, %d chars)...",
        metadata.get("cluster_id", "?"),
        metadata.get("message_count", 0),
        len(transcript),
    )

    # A6: Wire in learned amendment context for text claims
    system = TEXT_CLAIMS_SYSTEM_PROMPT
    if conversation_id:
        amendment_ctx = build_extraction_context(conversation_id, pass_name="claims")
        if amendment_ctx:
            system += f"\n\n{amendment_ctx}"
            logger.info("Appended amendment context (%d chars) to text claims prompt", len(amendment_ctx))

    response = client.messages.create(
        model=CLAIMS_MODEL,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    if response.stop_reason == "max_tokens":
        logger.warning(
            "Text extraction hit max_tokens (%d output tokens)",
            response.usage.output_tokens,
        )

    raw_text = response.content[0].text.strip()
    json_text = extract_json(raw_text)
    result = ClaimsResult.model_validate_json(json_text)

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    # Assign content-deterministic claim IDs
    _seen = set()
    for claim in result.claims:
        text_norm = (claim.claim_text or "").strip().lower()
        hash_input = "|".join([
            conversation_id,
            claim.claim_type or "",
            text_norm,
            claim.subject_name or "",
            claim.target_entity or "",
            claim.speaker or "",
        ])
        hash_hex = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:12]
        candidate = f"claim_{hash_hex}"
        suffix = 0
        while candidate in _seen:
            suffix += 1
            candidate = f"claim_{hash_hex}_{suffix}"
        _seen.add(candidate)
        claim.id = candidate

    # Instrumentation
    type_counts = {}
    eq_counts = {}
    for c in result.claims:
        type_counts[c.claim_type] = type_counts.get(c.claim_type, 0) + 1
        eq = getattr(c, "evidence_quality", None) or "unset"
        eq_counts[eq] = eq_counts.get(eq, 0) + 1

    logger.info(
        "Text extraction complete: %d claims | types=%s | evidence_quality=%s | "
        "%d memory writes, %d new contacts | "
        "%d in / %d out tokens",
        len(result.claims), type_counts, eq_counts,
        len(result.memory_writes), len(result.new_contacts_mentioned),
        usage["input_tokens"], usage["output_tokens"],
    )

    return result, usage
