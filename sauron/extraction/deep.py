"""Pass 3: Opus 4.6 Synthesis — deep reasoning from claims + vocal analysis.

Receives: claims from Sonnet + vocal analysis with baseline comparisons +
contact profiles + recent interaction history + existing beliefs.

Produces: vocal intelligence, belief updates, self-coaching, graph edges,
commitments (enriched), what-changed assessments. Does NOT extract claims —
that's Sonnet's job (Pass 2).

Cost: ~$0.13/conversation
"""

import json
import logging

import anthropic

from sauron.config import EXTRACTION_MODEL
from sauron.extraction.json_utils import extract_json
from sauron.extraction.schemas import (
    Claim,
    ClaimsResult,
    SoloExtractionResult,
    SynthesisResult,
    TriageResult,
)

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """You are Sauron, a personal intelligence synthesis engine for Stephen Andrews.

You receive:
1. Atomic claims extracted from a conversation (with evidence and confidence)
2. Per-speaker vocal analysis with baseline comparisons
3. Calendar context and triage classification
4. Existing beliefs about the people in this conversation (if any)

Your job is to SYNTHESIZE — not re-extract. The claims are already extracted.
You correlate claims with vocal data, identify belief updates, provide coaching,
and produce actionable intelligence.

Output valid JSON matching this schema:
{
  "summary": "3-5 sentence synthesis of the conversation — what happened, what matters, what changed",
  "relationship_notes": "Observation about relationship dynamics and trajectory",
  "vocal_intelligence_summary": "Key vocal finding correlating words with voice data",
  "word_voice_alignment": "aligned | misaligned | neutral",
  "sentiment": "warm | neutral | transactional | tense | enthusiastic",
  "relationship_delta": "strengthened | maintained | weakened | new",
  "per_speaker_vocal_insights": {
    "speaker_name": {
      "emotional_state": "description with specific vocal evidence",
      "rapport_assessment": "description",
      "engagement_trend": "description with specific moments",
      "communication_style_notes": "observed preferences and patterns",
      "topics_of_passion": ["topics where vocal engagement was high"],
      "topics_of_discomfort": ["topics with stress markers"]
    }
  },
  "belief_updates": [
    {
      "entity_type": "person | topic | organization | relationship | self",
      "entity_id": null,
      "entity_name": "Name or topic",
      "belief_key": "short_identifier_for_dedup",
      "belief_summary": "Natural language belief statement",
      "status": "active | provisional | refined | qualified | time_bounded | superseded | contested | stale",
      "confidence": 0.0-1.0,
      "evidence_role": "support | contradiction | refinement | qualification",
      "supporting_claim_ids": ["claim_001", "claim_003"]
    }
  ],
  "self_coaching": [
    {
      "observation": "What Stephen did well or could improve — be specific with vocal/behavioral evidence",
      "recommendation": "Specific actionable suggestion"
    }
  ],
  "graph_edges": [
    {
      "from_entity": "name or entity",
      "from_type": "person | topic | organization",
      "to_entity": "name or entity",
      "to_type": "person | topic | organization",
      "edge_type": "knows | works_with | reports_to | supports | opposes | interested_in | expert_on | etc",
      "strength": 0.0-1.0
    }
  ],
  "my_commitments": [
    {
      "description": "What Stephen committed to",
      "original_words": "exact quote from claims evidence",
      "resolved_date": "YYYY-MM-DD or null",
      "confidence": 0.0-1.0,
      "assignee": "Stephen",
      "direction": "i_owe",
      "source_claim_id": "claim_XXX"
    }
  ],
  "contact_commitments": [
    {
      "description": "What they committed to",
      "original_words": "exact quote",
      "resolved_date": "YYYY-MM-DD or null",
      "confidence": 0.0-1.0,
      "assignee": "person name",
      "direction": "they_owe",
      "source_claim_id": "claim_XXX"
    }
  ],
  "standing_offers": [{"contact_name": "...", "description": "...", "offered_by": "me|them", "original_words": "..."}],
  "scheduling_leads": [{"contact_name": "...", "description": "...", "original_words": "...", "timeframe": "..."}],
  "calendar_events": [
    {
      "title": "Event title",
      "suggested_date": "YYYY-MM-DD",
      "attendees": ["Person 1", "Person 2"],
      "original_words": "Verbatim scheduling language from transcript",
      "start_time": "ISO datetime if explicitly stated, empty if inferred",
      "end_time": "ISO datetime if explicitly stated, empty if inferred",
      "location": "Meeting location if mentioned",
      "is_placeholder": false,
      "source_claim_id": "claim_xxx if traceable"
    }
  ],
  "follow_ups": [{"description": "...", "priority": "high|medium|low", "due_date": "YYYY-MM-DD or null"}],
  "policy_positions": [{"person": "...", "topic": "...", "position": "supports|opposes|undecided", "strength": 0.0-1.0, "notes": "..."}],
  "topics_discussed": ["topic1", "topic2"],
  "what_changed": {
    "person_name": "Summary of what changed for this person since context indicates last interaction"
  },
    "provenance_observations": [
    {
      "contact_name": "Full Name",
      "introduced_by": "Name of introducer or null",
      "discovered_via": "referral | conference | cold_outreach | mutual_friend | colleague | conversation",
      "context": "Brief description of how the connection was established",
      "source_claim_id": "claim ID if traceable"
    }
  ],
  "status_changes": [
    {
      "contact_name": "Full Name",
      "change_type": "job_change | promotion | departure | relocation | title_change",
      "details": "Description of the status change",
      "effective_date": "Date if mentioned, or null",
      "from_state": "Previous state (e.g. 'VP at Goldman') or null if unknown",
      "to_state": "New state (e.g. 'MD at Morgan Stanley') or null if unknown",
      "source_claim_id": "claim ID if traceable"
    }
  ],
  "org_intelligence": [
    {
      "organization": "Organization Name",
      "intel_type": "restructuring | hiring | funding | policy_change | acquisition | expansion | industry_mention | org_relationship",
      "details": "Description of the organizational intelligence",
      "industry": "Normalized sector label for industry_mention type, or null",
      "related_org": "Other organization name for org_relationship type, or null",
      "relationship_type": "acquisition | partnership | subsidiary | competitor | regulator_of | null",
      "mentioned_by": "Contact name who mentioned it, or null",
      "source_claim_id": "claim ID if traceable",
      "org_category": "Industry category if discernible (fintech, banking, government, legal, consulting, tech, etc.) or null",
      "org_size": "Organization size if mentioned (startup, mid-market, enterprise, government_agency, etc.) or null"
    }
  ],
  "affiliation_mentions": [
    {
      "contact_name": "Full Name",
      "organization": "Organization Name",
      "title": "Their title/role at the org, or null",
      "department": "Department if mentioned, or null",
      "role_type": "Open-ended: executive, staff, consultant, board, advisor, partner, counsel, commissioner, chair, founder, investor, contractor, etc.",
      "is_current": true,
      "change_type": "new_role | departure | promotion | null (static mention)",
      "source_claim_id": "claim ID if traceable",
      "confidence": 0.7
    }
  ],
  "referenced_resources": [
    {
      "resource_type": "book | article | tool | website | framework | podcast | course | other",
      "title": "Resource title or name",
      "author": "Author if known, or null",
      "url": "URL if mentioned, or null",
      "description": "Brief description of the resource",
      "mentioned_by": "Speaker who mentioned it",
      "context": "Why it came up or why it is relevant",
      "contact_name": "Person most associated with this resource",
      "source_claim_id": "claim_xxx if traceable"
    }
  ],
  "asks": [
    {
      "ask_type": "direct_ask | soft_ask | implied_need | favor | introduction_request",
      "description": "What is being asked for",
      "original_words": "Verbatim words if available",
      "asked_by": "Speaker name",
      "asked_of": "Who is being asked (name or 'me')",
      "contact_name": "Contact name for routing purposes",
      "urgency": "low | medium | high",
      "status": "open | fulfilled | declined | deferred",
      "source_claim_id": "claim_xxx if traceable"
    }
  ],
  "life_events": [
    {
      "event_type": "marriage | birth | death | graduation | move | retirement | health | milestone | other",
      "description": "Brief description of the event",
      "contact_name": "Person the event is about",
      "approximate_date": "When it happened or will happen, or null",
      "source_claim_id": "claim_xxx if traceable"
    }
  ],
  "context_classification": "confirmed or refined classification"
}

Key instructions:
- BELIEVE THE CLAIMS. They are already extracted and evidence-linked. Build on them, don't re-extract.
- For vocal analysis: correlate specific vocal deviations with specific claims/moments.
- Word-voice misalignment: when claims say "fine/good" but vocal data shows jitter/stress spikes, flag it clearly.
- Self-coaching: analyze Stephen's talk-time ratio, question frequency, interruption patterns. Be specific.
- Belief updates: determine if existing beliefs should be supported, refined, qualified, contradicted, or if new beliefs emerge.
- Commitments: ONLY from claims of type "commitment". Include source_claim_id to link back. "We should..." is NOT a commitment.
- Graph edges: build from relationship claims and observed connections. Include person↔topic, person↔org, not just person↔person.
- What-changed: per person, summarize what's new/different compared to previous context.
- Sentiment: assess the overall emotional tone of the conversation. "warm" = friendly/personal, "neutral" = straightforward, "transactional" = business-only, "tense" = conflict/stress, "enthusiastic" = high energy/excitement.
- Relationship delta: assess whether the relationship moved. "strengthened" = closer/deeper, "maintained" = stable, "weakened" = strained/cooled, "new" = first meaningful interaction.
- Affiliation mentions: Extract when someone's organizational role is mentioned or implied.
  "John is now at Goldman" = affiliation with change_type="new_role".
  "Sarah from the SEC" = static mention (change_type=null).
  role_type is open-ended — use whatever fits: executive, staff, consultant, board, advisor, partner, counsel, commissioner, chair, founder, investor, contractor, etc.
  For Stephen Andrews: keep extraction conservative. Only emit Stephen's affiliation mentions when clearly relevant to system state or routing. Do not flood output with obvious default facts.
  Overlap with status_changes is OK — status_changes captures the event, affiliation_mentions captures the structured triple.
- Org intelligence expansion:
  "CME is a derivatives exchange" = industry_mention with industry="Market Infrastructure"
  "CME acquired NEX Group" = org_relationship with related_org="NEX Group", relationship_type="acquisition"
  For org_relationship: ALWAYS include the structured related_org and relationship_type fields. Do not flatten into free text only.
  Keep extraction conservative — only emit when clearly grounded in claims.
- Referenced resources: Extract books, articles, tools, websites, frameworks etc. mentioned in conversation. Only extract if clearly referenced — not passing mentions.
- Asks: Capture explicit requests, soft asks, implied needs, favors, and introduction requests. "Could you introduce me to..." = introduction_request. "We should look into..." = soft_ask (only if directed at someone). Do NOT conflate with commitments — asks are requests, commitments are promises.
- Life events: Extract significant personal events (marriage, birth, death, graduation, move, retirement, health milestones). Only when clearly mentioned, not inferred.
- Calendar events: Include original_words (verbatim scheduling language). If the model extracted an actual time, use start_time/end_time. If only a date or vague reference, set is_placeholder=true.
- Be specific, not generic. "Heath seemed stressed" is bad. "Heath's jitter +45% when discussing compliance deadline (claim_007) suggests elevated stress about timeline" is good.
"""

SOLO_EXTRACTION_SYSTEM_PROMPT = """You are Sauron, extracting intelligence from Stephen Andrews' solo voice captures.
These are recordings where Stephen is talking to himself — brainstorming, dictating tasks,
debriefing after meetings, journaling, or setting pre-meeting intentions.

Output valid JSON matching this schema:
{
  "summary": "brief summary of the solo capture",
  "solo_mode": "note|tasks|debrief|journal|prep|general",
  "tasks": ["specific action items dictated"],
  "ideas": ["ideas or insights captured"],
  "contact_follow_ups": [{"description": "...", "priority": "high|medium|low", "due_date": "YYYY-MM-DD or null"}],
  "strategic_insights": ["strategic observations"],
  "journal_prose": "reflective content if journal mode, else null",
  "pre_meeting_goals": ["goals for upcoming meeting if prep mode"],
  "linked_contact_names": ["names of people mentioned"]
}

Be thorough — capture every task, idea, and name mentioned.
"""


def synthesize(
    transcript_text: str,
    claims: ClaimsResult,
    vocal_summary: str | None = None,
    calendar_context: dict | None = None,
    triage: TriageResult | None = None,
    existing_beliefs: list[dict] | None = None,
    amendment_context: str = "",
    conversation_id: int | None = None,
) -> tuple[SynthesisResult, dict]:
    """Run Opus synthesis on claims + vocal analysis.

    Args:
        transcript_text: Formatted diarized transcript with speaker names.
        claims: ClaimsResult from Sonnet Pass 2.
        vocal_summary: Formatted vocal analysis with baseline comparisons.
        calendar_context: Calendar event context.
        triage: Haiku triage result.
        existing_beliefs: Current beliefs about people in this conversation.
        amendment_context: Learned preferences.

    Returns:
        (SynthesisResult, usage_dict)
    """
    client = anthropic.Anthropic()

    system = SYNTHESIS_SYSTEM_PROMPT
    if amendment_context:
        system += f"\n\n{amendment_context}"

    user_content = _build_synthesis_context(
        transcript_text, claims, vocal_summary,
        calendar_context, triage, existing_beliefs
    )

    # Wave 2: Inject known affiliation context for contacts in this conversation
    aff_context = _build_affiliation_context(conversation_id)
    if aff_context:
        user_content = f"## Known Affiliations\n{aff_context}\n\n---\n\n{user_content}"
    logger.info("Running Opus synthesis...")
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=16384,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    raw_text = extract_json(response.content[0].text)

    result = SynthesisResult.model_validate_json(raw_text)

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    logger.info(
        f"Synthesis complete: {len(result.belief_updates)} belief updates, "
        f"{len(result.my_commitments)} my commitments, "
        f"{len(result.contact_commitments)} their commitments, "
        f"{len(result.graph_edges)} graph edges, "
        f"{len(result.self_coaching)} coaching notes"
    )

    return result, usage


def solo_extract(
    transcript_text: str,
    triage: TriageResult | None = None,
    amendment_context: str = "",
) -> tuple[SoloExtractionResult, dict]:
    """Run extraction on a solo capture (single speaker)."""
    client = anthropic.Anthropic()

    system = SOLO_EXTRACTION_SYSTEM_PROMPT
    if amendment_context:
        system += f"\n\n{amendment_context}"

    user_content = f"Solo capture transcript:\n\n{transcript_text}"
    if triage and triage.solo_mode:
        user_content += f"\n\nDetected solo mode: {triage.solo_mode}"

    logger.info("Running solo extraction...")
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    raw_text = extract_json(response.content[0].text)

    result = SoloExtractionResult.model_validate_json(raw_text)

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    logger.info(
        f"Solo extraction complete: {len(result.tasks)} tasks, "
        f"{len(result.ideas)} ideas, {len(result.contact_follow_ups)} follow-ups"
    )

    return result, usage



def _build_affiliation_context(conversation_id: int | None = None) -> str:
    """Build affiliation context string for contacts in a conversation.

    Only includes affiliations for contacts actually present in the conversation.
    Prioritizes current affiliations over former ones.
    Does NOT dump unrelated org history into every prompt.

    Returns a concise block like:
      Known affiliations:
      - John Smith: VP of Trading at Goldman Sachs (Market Infrastructure)
      - Sarah Jones: Commissioner at CFTC (Government/Regulatory)
    """
    if conversation_id is None:
        return ""

    try:
        from sauron.db.connection import get_connection
        conn = get_connection()

        # Get contacts involved in this conversation (from claims)
        contacts = conn.execute("""
            SELECT DISTINCT uc.id, uc.canonical_name
            FROM event_claims ec
            JOIN unified_contacts uc ON ec.subject_entity_id = uc.id
            WHERE ec.conversation_id = ?
        """, (conversation_id,)).fetchall()

        if not contacts:
            conn.close()
            return ""

        lines = []
        for c in contacts:
            affs = conn.execute("""
                SELECT org_name, org_industry, title, role_type, is_current
                FROM contact_affiliations_cache
                WHERE unified_contact_id = ?
                ORDER BY is_current DESC, synced_at DESC
            """, (c["id"],)).fetchall()

            # Prioritize current affiliations; include at most 2 per person
            shown = 0
            for a in affs:
                if shown >= 2:
                    break
                role_str = a["title"] or a["role_type"] or "affiliated"
                industry_str = f" ({a['org_industry']})" if a["org_industry"] else ""
                current_str = "" if a["is_current"] else " [former]"
                lines.append(f"- {c['canonical_name']}: {role_str} at {a['org_name']}{industry_str}{current_str}")
                shown += 1

        conn.close()

        if not lines:
            return ""

        return "Known affiliations:\n" + "\n".join(lines)
    except Exception:
        logger.debug("Could not build affiliation context", exc_info=True)
        return ""


def _build_synthesis_context(
    transcript_text: str,
    claims: ClaimsResult,
    vocal_summary: str | None,
    calendar_context: dict | None,
    triage: TriageResult | None,
    existing_beliefs: list[dict] | None,
) -> str:
    """Build the full context package for Opus synthesis."""
    parts = []

    if calendar_context:
        parts.append(f"## Calendar Context\n{json.dumps(calendar_context, indent=2)}")

    if triage:
        episode_info = ""
        if triage.episodes:
            episode_lines = [
                f"  - [{ep.start_time:.0f}-{ep.end_time:.0f}s] {ep.episode_type}: {ep.title}"
                for ep in triage.episodes
            ]
            episode_info = "\nEpisodes:\n" + "\n".join(episode_lines)

        parts.append(
            f"## Triage Classification\n"
            f"Context: {triage.context_classification}\n"
            f"Value: {triage.value_assessment}\n"
            f"Speakers: {triage.speaker_count}\n"
            f"Topics: {', '.join(triage.topic_tags)}"
            f"{episode_info}"
        )

    # Claims from Sonnet — the primary input
    claims_json = []
    for c in claims.claims:
        claims_json.append(c.model_dump(exclude_none=True))
    parts.append(
        f"## Extracted Claims ({len(claims.claims)} total)\n\n"
        f"```json\n{json.dumps(claims_json, indent=2)}\n```"
    )

    if claims.memory_writes:
        writes_json = [m.model_dump() for m in claims.memory_writes]
        parts.append(
            f"## Memory Writes ({len(claims.memory_writes)})\n\n"
            f"```json\n{json.dumps(writes_json, indent=2)}\n```"
        )

    if existing_beliefs:
        parts.append(
            f"## Existing Beliefs About People in This Conversation\n\n"
            f"```json\n{json.dumps(existing_beliefs, indent=2)}\n```"
        )

    parts.append(f"## Diarized Transcript\n\n{transcript_text}")

    if vocal_summary:
        parts.append(f"## Vocal Analysis (with baseline comparisons)\n\n{vocal_summary}")

    return "\n\n---\n\n".join(parts)
