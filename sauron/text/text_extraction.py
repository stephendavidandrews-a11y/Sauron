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
- Group chat clusters: bias ONE LANE LOWER than you otherwise would (more conservative)
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
    client = anthropic.Anthropic()

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

TEXT_CLAIMS_SYSTEM_PROMPT = """You are a claims extraction system for a personal text intelligence platform owned by Stephen Andrews.
You receive a formatted text message conversation and must extract ATOMIC CLAIMS.

This is TEXT (iMessage/SMS), not voice. Key differences from voice:
- Evidence references are LINE NUMBERS, not timestamps
- No vocal/audio analysis available
- Text is often compressed, abbreviated, ambiguous
- Reactions (👍, ❤️) and shared links are meaningful signals
- Every claim MUST include an evidence_quality rating

═══════════════════════════════════════════════════════════════
STAGE 1: CANDIDATE DETECTION
═══════════════════════════════════════════════════════════════

Scan the conversation and identify everything worth capturing:
- Factual statements (names, dates, places, roles, details)
- Positions and opinions
- Commitments and half-commitments ("I'll try to..." counts)
- Preferences and habits
- Relationship signals
- Contextual observations
- Tactical reads

When uncertain whether something matters, include it at lower confidence.

═══════════════════════════════════════════════════════════════
STAGE 2: NORMALIZATION
═══════════════════════════════════════════════════════════════

For each candidate, assign structured fields:

claim_type — STRICT definitions:
  - fact: Descriptive statement about reality
  - position: View, opinion, or stance on an issue
  - commitment: Promise, task, or obligation (half-commitments count at lower confidence)
  - preference: Likes, dislikes, habits, communication style
  - relationship: Connection, trust, alignment, or tension between people
  - observation: Context-bound read from this specific interaction
  - tactical: Actionable inference about approach

evidence_quality — CRITICAL for text claims:
  - explicit: Directly stated in the message. "I'll send the memo by Friday."
  - abbreviated: Likely true but expressed in compressed form. "k will do" probably means agreement.
  - ambiguous: Could go multiple ways. "sounds good" could be enthusiasm, polite deflection, or sarcasm.
  - inferred: Derived from behavioral patterns rather than explicit statements.
    Message volume changes, punctuation shifts, formality changes.

modality:
  - stated: Explicitly written in the text
  - inferred: Logically inferred from context (lower confidence)
  - implied: Implied by behavior or patterns (lowest confidence)

confidence: 0-1
  - 0.9+ for explicit statements with explicit evidence
  - 0.7-0.9 for abbreviated but clear intent
  - 0.5-0.7 for ambiguous or inferred claims
  - For inferred claims: default LOWER than stated claims

stability: stable_fact | soft_inference | transient_observation

═══════════════════════════════════════════════════════════════
COMMITMENT CLASSIFICATION
═══════════════════════════════════════════════════════════════

firmness levels (highest to lowest):

  REQUIRED: Someone specific (family, partner, colleague, client) is DEPENDING
    on delivery, and failure would damage trust, block their work, or break a promise.
    REQUIRED is triggered when TWO OR MORE of these are present:
    (a) A specific deliverable or action is named
    (b) A recipient/beneficiary is identified (person or group counting on it)
    (c) A deadline exists (explicit date or inferable from context)
    (d) The framing implies obligation ("I need to", "I will", "I owe you")
    Examples:
    - "I'll have the draft to you by Friday" → REQUIRED (deliverable + recipient + deadline)
    - "I need to call Mom this weekend" → REQUIRED (relational obligation + deadline)
    - "I'll go back to Grassley with a whip count" → REQUIRED (deliverable + recipient)
    - "The filing is due March 31" → REQUIRED (external deadline + obligation)

  CONCRETE: Clear stated intent to do something, but self-directed.
    "I'll sleep on this." "I'll follow up with her." "I owe you a call."
    No external party is counting on specific delivery.

  INTENTIONAL: "I plan to..." / "I'm going to..." — genuine but unbounded.

  TENTATIVE: "I might..." / "Maybe I'll..." — hedged, conditional.

  SOCIAL: "We should grab coffee sometime" — social filler, no real commitment.

Additional commitment rules:
- "I will" / "I'll" / "let me" = at least INTENTIONAL
- "I want to" / "I should" = NOT a commitment (desire/aspiration language)
- "We should grab coffee" = NOT a commitment (scheduling_lead observation)
- "We can discuss more on Monday" = CONCRETE (mutual plan, not a deliverable owed)
- "Let me check on that and get back to you" = CONCRETE (common polite phrase,
  not obligation-framing unless context makes it clearly depended upon)

═══════════════════════════════════════════════════════════════
COMMITMENT DATE RESOLUTION
═══════════════════════════════════════════════════════════════

For ALL commitments, resolve dates when possible:

due_date: YYYY-MM-DD resolved date. Use the CLUSTER DATE provided in metadata
to resolve relative references:

  - "Monday" → nearest future Monday from cluster date
  - "this Friday" on a Friday → today (the cluster date)
  - "next Friday" → NEXT WEEK's Friday (always), flag date_confidence: approximate
  - "by end of week" → this Friday
  - "by end of month" → last day of current month
  - "tomorrow" → day after cluster date
  - "this weekend" → Saturday of cluster week
  - "Q2" → 2026-06-30, date_confidence: approximate
  - "in a couple weeks" → +14 days, date_confidence: approximate

date_confidence:
  - exact: Specific date stated or unambiguously resolvable ("by Friday March 14")
  - approximate: Resolved but with some uncertainty ("in a couple weeks", "next Friday")
  - conditional: Date depends on an external event ("after we talk to Schmitt")
  - null_explained: No date inferable; date_note explains why

date_note: Free text context for non-exact dates. Examples:
  - "after Schmitt conversation"
  - "pending congressional recess schedule"
  - "every Monday recurring"
  - "dependent on WH OLA response"

condition_trigger: For conditional commitments, describe what event would resolve
the condition: "Conversation with Senator Schmitt about chatbot bill amendments"

recurrence: For recurring commitments, the pattern:
  - "weekly:monday" / "monthly:first_tuesday" / "daily" / "biweekly:friday"
  - due_date holds the NEXT occurrence

related_claim_id: When two claims in the same cluster are clearly paired (an ask
and its corresponding offer, a question and its answer, a condition and the
action it triggers), link them by setting related_claim_id on BOTH claims to
point to each other.

═══════════════════════════════════════════════════════════════
TEXT-SPECIFIC EXTRACTION RULES
═══════════════════════════════════════════════════════════════

1. Short or abbreviated messages ("k", "sounds good", "👍") should be assigned
   evidence_quality "abbreviated" or "ambiguous", NOT "explicit".

2. Prefer fewer high-quality claims over many speculative ones. When evidence
   is thin, mark as "inferred" rather than skipping — the review system gates it.

3. For logistical-only content (time/place coordination, simple confirmations),
   output zero claims. This is normal and expected.

4. Emotional and behavioral observations are valid from text, but ONLY when based
   on clear evidence: explicit statements ("I'm upset") or strong patterns (sudden
   formality shift from someone normally casual). NEVER infer emotional states
   from a single short message.

5. Reactions (👍, ❤️, etc.) are meaningful signals. When a reaction references a
   specific message, note WHAT was reacted to in the claim:
   - 👍 to "I'll send the draft" = acknowledgment of that commitment
   - 😢 to "Practice is canceled" = negative reaction to the cancellation
   - But reactions alone are rarely worth a standalone claim unless they reveal
     a position or preference

6. Shared links, images, and attachments: note them as context in claims that
   reference them. When a claim is a RESPONSE to a shared image or link, mention
   that in the claim text: "Mary Jo prefers fewer candles in the wedding table
   design, reacting to Catherine's AI-generated mockup image."

7. For relationship, observation, and tactical claims: prefer explicit evidence.
   When evidence is pattern-based (message frequency, punctuation changes),
   mark as evidence_quality "inferred".

═══════════════════════════════════════════════════════════════
MULTI-STATEMENT PARSING
═══════════════════════════════════════════════════════════════

A single message may contain MULTIPLE independent statements. Extract each
as a separate claim. Common patterns:

- Correction + new fact: "No no, I was joking about that. Practice IS canceled."
  → Two claims: (1) earlier statement was a joke, (2) practice is canceled (fact)
- Concession + position: "You might be right about the candles, but I still want more."
  → Two claims: (1) partial concession, (2) maintained position
- Status update + next step: "Schmitt is leaning no. I'll talk to Ethan about amendments."
  → Two claims: (1) Schmitt's position, (2) commitment to talk to Ethan

Do NOT collapse multi-statement messages into a single claim.

═══════════════════════════════════════════════════════════════
SUBJECT MATTER LINKING
═══════════════════════════════════════════════════════════════

When a claim discusses actions, decisions, or commitments related to a specific
project, initiative, bill, case, deal, event, or workstream, IDENTIFY that subject
matter and include it in the claim text. The reader should understand WHAT THIS IS
ABOUT without needing to read the full transcript.

BAD: "Will is uncertain how much to edit the manager's amendment"
GOOD: "Will Simpson is uncertain how much to edit the GUARD Act manager's
       amendment without a promise of Schmitt's support"

BAD: "Mary Jo prefers fewer candles"
GOOD: "Mary Jo prefers fewer candles in the wedding dinner table design"

BAD: "Catherine committed to sleeping on the decision"
GOOD: "Catherine committed to sleeping on the wedding table candle density decision"

═══════════════════════════════════════════════════════════════
ENTITY RECOGNITION
═══════════════════════════════════════════════════════════════

When a claim mentions a person or organization not in the participant roster,
note them appropriately:

- Senators, officials, public figures: use full title + name in claim text
  ("Senator Schmitt", "Senator Grassley", not just "Schmitt")
- Organizations: use full name when identifiable ("White House Office of
  Legislative Affairs", not just "WH OLA")
- First-name-only references: if the person is identifiable from context
  (e.g., "Ethan" discussed in relation to Schmitt's office = likely a staffer),
  flag as new_contact with available context
- Teams/groups: note as organizations when they function as entities
  ("the team" = an identifiable work group)

═══════════════════════════════════════════════════════════════
NAME DISAMBIGUATION — CRITICAL
═══════════════════════════════════════════════════════════════

A PARTICIPANT ROSTER is provided at the top of each extraction request.
It maps display names to identified contacts.

RULES:
1. ALWAYS use the FULL NAME from the roster for subject_name and speaker
2. When multiple participants share a first name, disambiguate with full names
3. Relational terms ("my brother") → resolve to actual names if possible
4. For sent messages from STEPHEN → speaker is "Stephen Andrews"

*** CRITICAL — subject_name vs speaker ***
subject_name = the person the claim is ABOUT (who is being described, who
               performed the action, whose position/preference/commitment it is)
speaker      = the person who WROTE the message containing the information

These are OFTEN DIFFERENT. When someone reports information about a third
party, the subject is the third party, NOT the speaker.

EXAMPLES:
  Message from Will Simpson: "Senator Schmitt is leaning no on the bill"
    → subject_name: "Senator Schmitt"  (claim is ABOUT Schmitt)
    → speaker: "Will Simpson"          (Will is reporting it)

  Message from Will Simpson: "I'll send the memo by Friday"
    → subject_name: "Will Simpson"     (claim is about Will's own commitment)
    → speaker: "Will Simpson"          (Will said it)

  Message from Sarah: "Grassley's office wants a revised draft"
    → subject_name: "Senator Grassley" (claim is about Grassley's desire)
    → speaker: "Sarah"                 (Sarah is reporting it)

  Message from Stephen: "Heath told me he's leaving Treasury"
    → subject_name: "Heath"            (claim is about Heath leaving)
    → speaker: "Stephen Andrews"       (Stephen is reporting it)

WRONG: Setting subject_name to the speaker when the claim describes
       someone else. If Will says "Schmitt is opposed", subject_name
       is Schmitt, NOT Will.

*** people_mentioned — COMPREHENSIVE ***
Include ALL people referenced in the conversation, including:
- All conversation participants (sender and recipients)
- All third parties mentioned by name (senators, staffers, etc.)
- People referenced indirectly if identifiable ("his chief of staff" = name if known)"

═══════════════════════════════════════════════════════════════
SUBJECT TYPE
═══════════════════════════════════════════════════════════════

Determine whether the claim is primarily about a person, organization, legislation, or topic.

subject_type: "person" | "organization" | "legislation" | "topic"

Rules:
- "person" (default): The claim describes a person's action, position, commitment, or state
  e.g., "Will believes the bill will pass" → subject_type="person", subject_name="Will Simpson"
- "legislation": The claim is fundamentally about a bill, law, regulation, or rule
  e.g., "The GUARD Act won't make the markup" → subject_type="legislation", subject_name="GUARD Act"
  e.g., "The Wyden-Durbin bill covers transportation" → subject_type="legislation", subject_name="Wyden-Durbin bill"
- "organization": The claim is about an org's action, state, or policy
  e.g., "CFTC is restructuring the Division of Enforcement" → subject_type="organization", subject_name="CFTC"
  e.g., "Allstate is hiring a new government affairs lead" → subject_type="organization", subject_name="Allstate"
- "topic": The claim is about a general topic, project, or event
  e.g., "The Senate markup is scheduled for March 19" → subject_type="topic", subject_name="Senate markup"
  e.g., "DeFi regulation is stalling" → subject_type="topic", subject_name="DeFi regulation"

IMPORTANT: The speaker is ALWAYS captured in the "speaker" field regardless of subject_type.
If Will Simpson reports "The GUARD Act won't make the markup":
  subject_type="legislation", subject_name="GUARD Act", speaker="Will Simpson"

When uncertain between person and non-person, prefer person. Most claims are about people.

═══════════════════════════════════════════════════════════════
ADDITIONAL ENTITIES
═══════════════════════════════════════════════════════════════

For each claim, identify ALL people involved beyond the primary subject_name.

additional_entities: [
  {"name": "Full Name", "role": "co_subject | target | beneficiary"}
]

Rules:
- co_subject: Both people are equally the subject of the claim
  e.g., "Stephen and Catherine are engaged" → subject_name="Stephen Andrews",
        additional_entities=[{"name": "Catherine Cole", "role": "co_subject"}]
  e.g., "Will and Daniel will draft the memo together" → subject_name="Will Simpson",
        additional_entities=[{"name": "Daniel Park", "role": "co_subject"}]
- target: The person being acted upon, told about, or referenced
  e.g., "Stephen invited Catherine to golf" → subject_name="Stephen Andrews",
        additional_entities=[{"name": "Catherine Cole", "role": "target"}]
  e.g., "Will told Grassley about the bill" → subject_name="Will Simpson",
        additional_entities=[{"name": "Chuck Grassley", "role": "target"}]
- beneficiary: Person who benefits from the action
  e.g., "Daniel is drafting the memo for Grassley" → subject_name="Daniel Park",
        additional_entities=[{"name": "Chuck Grassley", "role": "beneficiary"}]
- OMIT additional_entities (or set to null/[]) when the claim is truly about one person only
- OMIT the speaker if they are only reporting, not participating in the claim
- Only add PEOPLE, not organizations/bills/topics — those go in target_entity
- Use FULL NAMES from the participant roster

═══════════════════════════════════════════════════════════════
STAGE 3: FILTER
═══════════════════════════════════════════════════════════════

Remove:
- Generic pleasantries ("How was your weekend?")
- Redundant filler
- Weak vibes with no tactical/relational value
- Claims already captured more cleanly by another candidate
- Restatements of widely known facts

Emit surviving claims as final output.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

Output ONLY valid JSON — no preamble, no commentary, no markdown fences:
{
  "claims": [
    {
      "id": "claim_001",
      "claim_type": "fact | position | commitment | preference | relationship | observation | tactical",
      "claim_text": "Natural language claim — one atomic statement. Include subject matter context.",
      "subject_entity_id": null,
      "subject_name": "Person or entity the claim is about (full name from roster if person)",
      "subject_type": "person | organization | legislation | topic",
      "target_entity": "What the claim references or null",
      "speaker": "Who wrote this message (full name from roster)",
      "modality": "stated | inferred | implied",
      "polarity": "positive | negative | neutral | mixed",
      "confidence": 0.0-1.0,
      "stability": "stable_fact | soft_inference | transient_observation",
      "importance": 0.0-1.0,
      "evidence_type": "quote | paraphrase | interaction_derived",
      "evidence_quote": "Exact words from the text message",
      "evidence_start": null,
      "evidence_end": null,
      "evidence_quality": "explicit | abbreviated | ambiguous | inferred",
      "review_after": null,
      "firmness": "required | concrete | intentional | tentative | social | null",
      "has_specific_action": "true | false | null",
      "has_deadline": "true | false | null",
      "has_condition": "true | false | null",
      "condition_text": "null or description of the condition",
      "direction": "owed_by_me | owed_to_me | owed_by_other | mutual | null",
      "time_horizon": null,
      "due_date": "YYYY-MM-DD or null",
      "date_confidence": "exact | approximate | conditional | null_explained | null",
      "date_note": "Context for non-exact dates or null",
      "condition_trigger": "What event resolves a conditional commitment, or null",
      "recurrence": "weekly:monday | monthly:first_tuesday | null",
      "related_claim_id": "ID of paired claim in same cluster, or null",
      "additional_entities": [{"name": "Full Name", "role": "co_subject | target | beneficiary"}]
    }
  ],
  "memory_writes": [
    {
      "entity_type": "person | topic | organization | self",
      "entity_id": null,
      "entity_name": "Name",
      "field": "field_name",
      "value": "The factual detail — include subject matter context",
      "source_quote": "Exact words"
    }
  ],
  "people_mentioned": ["Full Name of every person referenced, including non-participants"],
  "new_contacts_mentioned": [
    {
      "name": "Full Name or best available (e.g., 'Ethan')",
      "organization": "Organization if identifiable",
      "title": null,
      "context": "Brief context including subject matter: 'Staffer working on chatbot bill amendments with Schmitt's office'",
      "connectionTo": "Name of person who knows them",
      "mentionedBy": "Speaker who mentioned them",
      "source_claim_id": "claim_xxx",
      "introduced_by": null
    }
  ]
}
"""


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
    client = anthropic.Anthropic()

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

    response = client.messages.create(
        model=CLAIMS_MODEL,
        max_tokens=8192,
        system=TEXT_CLAIMS_SYSTEM_PROMPT,
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
