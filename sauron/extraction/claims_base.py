"""Shared claims extraction prompt base — used by both voice and text pipelines.

Contains the sections that are identical (or nearly so) between voice and text:
- Stage 1: Candidate Detection
- Stage 2: Normalization (claim types, modality, confidence, stability)
- Commitment Classification (with required tier)
- Commitment Date Resolution
- Subject Type
- Additional Entities
- Name Disambiguation
- Stage 3: Filter
- Output Format
"""

# ═══════════════════════════════════════════════════════════════
# STAGE 1: Candidate Detection (shared)
# ═══════════════════════════════════════════════════════════════

STAGE1_CANDIDATE_DETECTION = """
═══════════════════════════════════════════════════════════════
STAGE 1: CANDIDATE DETECTION
═══════════════════════════════════════════════════════════════

First, scan each episode and identify everything that might be worth capturing. Be generous. Include anything that could be a factual detail, a position, a commitment, a preference, a relationship signal, or a tactical observation.

When uncertain whether something matters, include it. It is better to extract something marginal at low confidence than to miss something useful.

Candidates should include:
- Factual statements (names, dates, places, roles, family details, career facts)
- Positions and opinions (even weakly stated)
- Commitments and half-commitments ("I'll try to..." counts)
- Preferences and habits
- Relationship signals (warmth, tension, alignment, distance)
- Contextual observations worth noting
- Tactical reads on how to approach someone
"""

# ═══════════════════════════════════════════════════════════════
# STAGE 2: Normalization (shared)
# ═══════════════════════════════════════════════════════════════

STAGE2_NORMALIZATION = """
═══════════════════════════════════════════════════════════════
STAGE 2: NORMALIZATION
═══════════════════════════════════════════════════════════════

For each candidate from Stage 1, assign structured fields:

claim_type — STRICT definitions, do not blur:
  - fact: Descriptive statement about reality. "Sarah has a daughter applying to colleges." "Mark moved to Treasury in January."
  - position: View, opinion, or stance on an issue. "Heath is skeptical of the current stablecoin draft."
  - commitment: Promise, task, or obligation. "Sarah will draft the enforcement memo by Friday." Half-commitments ("I'll try to...") count at lower confidence.
  - preference: Likes, dislikes, habits, communication style. "Jennifer prefers direct communication over small talk."
  - relationship: Connection, trust, alignment, or tension between people. Must involve at least two entities. "Sarah and Mark are aligned on Part 39." Relationship claims should capture how two specific people relate — not generic observations about someone's demeanor.
  - observation: Context-bound descriptive read from a specific interaction NOT yet strong enough to become relationship, tactical, or preference memory. "He seemed rushed at the end." observation must NOT swallow tactical advice, relationship inferences, stable preferences, or broad personality summaries.
  - tactical: Actionable inference about how Stephen should approach a specific person, topic, or situation. Must be specific and actionable. NOT generic vibe reads, broad personality summaries, or weak social impressions.

claim_text — Natural language, one sentence
subject_entity_id — null (resolved downstream)
subject_name — Person or entity the claim is about
target_entity — What the claim references (topic, person, org) or null
speaker — Who said this
modality:
  - stated: Explicitly said in the transcript
  - inferred: Logically inferred from what was said (be cautious, fewer of these, lower confidence)
  - implied: Implied by behavior, tone, or conversational dynamics (lowest confidence)
polarity: positive | negative | neutral | mixed
confidence: 0-1
  - 0.9+ for explicit statements
  - 0.7-0.9 for clear implications
  - 0.5-0.7 for inferences
  - For inferred claims: default LOWER than stated claims
stability: stable_fact | soft_inference | transient_observation
importance: 0-1 provisional — does this affect future action, relationship management, or what Stephen should know?
evidence_type:
  - quote: Claim backed by exact words from transcript (high trust)
  - paraphrase: Claim backed by rephrased content (moderate trust)
  - interaction_derived: Claim inferred from interaction patterns, vocal cues, behavioral signals (lower trust)
evidence_quote — Exact words or close paraphrase supporting the claim
evidence_start / evidence_end — Start/end timestamps from the transcript's [start-end] markers
"""

# ═══════════════════════════════════════════════════════════════
# Commitment Classification (shared, includes required tier)
# ═══════════════════════════════════════════════════════════════

COMMITMENT_CLASSIFICATION = """
═══════════════════════════════════════════════════════════════
COMMITMENT EXTRACTION RULES
═══════════════════════════════════════════════════════════════

For every statement that could be a commitment, promise, obligation, plan, or agreement,
extract it as a commitment-type claim with structured metadata.

CLASSIFICATION THRESHOLD: "Is there a specific future action stated by an identifiable person?"
- YES + commitment language ("I will", "I'll", "let me") → at least INTENTIONAL
- YES + commitment language + deadline or timeframe → CONCRETE
- YES + but depends on external contingency → TENTATIVE
- NO specific action, just social/future goodwill → SOCIAL

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

CRITICAL DISTINCTION — Commitment vs. desire language:
- "I'll look into that" = INTENTIONAL (commitment language + specific action)
- "I want to look into that" = NOT a commitment (desire language)
- "I should probably check on that" = NOT a commitment (aspiration)
- "Let me send that over" = INTENTIONAL (commitment language + specific action)
- "I'd love to send that" = NOT a commitment (desire language)

When uncertain between intentional and tentative, prefer intentional.
When uncertain between intentional and social, ask: is there a specific action? If yes, intentional. If no, social.
When uncertain whether desire language constitutes a real commitment, do NOT classify as commitment.

For each commitment claim, populate ALL of these fields:
- firmness: required | concrete | intentional | tentative | social
- has_specific_action: true | false
- has_deadline: true | false
- has_condition: true | false
- condition_text: the contingency if present, null otherwise
- direction: owed_by_me | owed_to_me | owed_by_other | mutual
  (from Stephen Andrews' perspective: owed_by_me = Stephen committed, owed_to_me = they committed to Stephen)
- time_horizon: ISO date | rough timeframe | none

For NON-commitment claims, set all commitment fields to null.

Rules:
- One claim per atomic statement. "Heath supports the GENIUS Act and thinks it will pass" = TWO claims.
- ALWAYS include evidence_quote with exact words from the transcript.
- Commitments MUST include original words in evidence_quote.
- "We should grab coffee" is NOT a commitment — it is a scheduling_lead observation.
- For inferred claims: be cautious, extract fewer, phrase with restraint, default to lower confidence than stated claims.
- Optimize for HIGH RECALL. Missed useful claims are worse than slightly noisy claims at low confidence.
"""

# ═══════════════════════════════════════════════════════════════
# Commitment Date Resolution (shared)
# ═══════════════════════════════════════════════════════════════

COMMITMENT_DATE_RESOLUTION = """
═══════════════════════════════════════════════════════════════
COMMITMENT DATE RESOLUTION
═══════════════════════════════════════════════════════════════

For ALL commitments, resolve dates when possible:

due_date: YYYY-MM-DD resolved date. Use context to resolve relative references:

  - "Monday" → nearest future Monday
  - "this Friday" on a Friday → today
  - "next Friday" → NEXT WEEK's Friday (always), flag date_confidence: approximate
  - "by end of week" → this Friday
  - "by end of month" → last day of current month
  - "tomorrow" → day after today
  - "this weekend" → Saturday
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

condition_trigger: For conditional commitments, describe what event would resolve
the condition: "Conversation with Senator Schmitt about chatbot bill amendments"

recurrence: For recurring commitments, the pattern:
  - "weekly:monday" / "monthly:first_tuesday" / "daily" / "biweekly:friday"
  - due_date holds the NEXT occurrence

related_claim_id: When two claims in the same batch are clearly paired (an ask
and its corresponding offer, a question and its answer, a condition and the
action it triggers), link them by setting related_claim_id on BOTH claims to
point to each other.
"""

# ═══════════════════════════════════════════════════════════════
# Name Disambiguation (shared)
# ═══════════════════════════════════════════════════════════════

NAME_DISAMBIGUATION = """
═══════════════════════════════════════════════════════════════
NAME DISAMBIGUATION (CRITICAL)
═══════════════════════════════════════════════════════════════

A PARTICIPANT ROSTER is provided at the top of each extraction request.
It maps transcript speaker labels to specific identified people, and lists
all known participants with their full names.

RULES — you MUST follow all of these:

1. ALWAYS use the FULL NAME from the participant roster for subject_name
   and speaker fields. Never use just a first name if the roster provides
   a full name. Example: use "Stephen Andrews" not "Stephen".

2. When multiple participants share a first name (e.g., two Stephens,
   two Sarahs), you MUST use full names to disambiguate EVERY reference.
   Never leave it ambiguous.

3. If the transcript says "Stephen" and the roster lists both
   "Stephen Andrews" and "Stephen Weber", determine from CONTEXT which
   person is being discussed:
   - Who is speaking? (check the speaker label mapping)
   - What is the topic? (family context → likely Stephen Weber;
     work/CFTC context → likely Stephen Andrews)
   - What pronouns or relational terms are used?
   If you cannot determine which Stephen, use the full name of whoever
   is most likely and set confidence lower (0.5-0.6).

4. For the speaker field: use the EXACT name from the participant roster
   that maps to the transcript's speaker label. If the transcript shows
   "Stephen Andrews: I talked to my dad", the speaker is "Stephen Andrews"
   and the subject of the claim about "my dad" should use the dad's full
   name from the roster if identifiable.

5. Relational terms ("my brother", "his wife", "their boss") should be
   resolved to the actual person's name using the participant roster's
   relationship context when possible. If you cannot resolve, keep the
   relational term as subject_name — the entity resolver will handle it
   downstream.

6. For unrecognized people mentioned in conversation who are NOT in the
   participant roster, use whatever name is given in the transcript.
   These will be flagged as provisional contacts downstream.

7. subject_name is the person PERFORMING THE ACTION or being described,
   NOT the person who reported or said it. The speaker field captures
   who said it. Example: if Daniel Park says "Wyden plans to introduce
   the bill Thursday", the subject_name is "Wyden" (the person acting),
   NOT "Daniel Park" (the speaker). Do NOT create duplicate claims about
   the same fact attributed to different subjects.
"""

# ═══════════════════════════════════════════════════════════════
# Subject Type (shared)
# ═══════════════════════════════════════════════════════════════

SUBJECT_TYPE = """
═══════════════════════════════════════════════════════════════
SUBJECT TYPE
═══════════════════════════════════════════════════════════════

CRITICAL — subject_type MUST be set correctly for every claim. Do NOT default everything to "person".

subject_type: "person" | "organization" | "legislation" | "topic"

Ask: "Who or what is this claim FUNDAMENTALLY about?"

- "person": The grammatical subject is a human individual
  e.g., "Will believes the bill will pass" → subject_type="person", subject_name="Will Simpson"
- "organization": The grammatical subject is an org, agency, company, or institution
  e.g., "CFTC is restructuring the Division of Enforcement" → subject_type="organization", subject_name="CFTC"
  e.g., "Allstate is hiring a new government affairs lead" → subject_type="organization", subject_name="Allstate"
  e.g., "The SEC issued new guidance" → subject_type="organization", subject_name="SEC"
- "legislation": The grammatical subject is a bill, law, regulation, or rule
  e.g., "The GUARD Act won't make the markup" → subject_type="legislation", subject_name="GUARD Act"
  e.g., "The Wyden-Durbin bill covers transportation" → subject_type="legislation", subject_name="Wyden-Durbin bill"
- "topic": The grammatical subject is an event, project, or abstract concept
  e.g., "The Senate markup is scheduled for March 19" → subject_type="topic", subject_name="Senate markup"
  e.g., "DeFi regulation is stalling" → subject_type="topic", subject_name="DeFi regulation"

IMPORTANT: The speaker is ALWAYS captured in the "speaker" field regardless of subject_type.
If Will Simpson reports "The GUARD Act won't make the markup":
  subject_type="legislation", subject_name="GUARD Act", speaker="Will Simpson"

Do NOT default to "person" when the claim is clearly about an org, law, or topic.
When genuinely ambiguous (e.g., "Stephen said CFTC is restructuring"), the
subject is CFTC (organization), not Stephen (person). Stephen is the speaker.
"""

# ═══════════════════════════════════════════════════════════════
# Additional Entities (shared)
# ═══════════════════════════════════════════════════════════════

ADDITIONAL_ENTITIES = """
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
"""

# ═══════════════════════════════════════════════════════════════
# Stage 3: Filter (shared)
# ═══════════════════════════════════════════════════════════════

STAGE3_FILTER = """
═══════════════════════════════════════════════════════════════
STAGE 3: FILTER
═══════════════════════════════════════════════════════════════

Remove any candidates that are:
- Generic pleasantries ("How was your weekend?" "Good to see you")
- Redundant filler or social grease
- Weak vibes with no tactical or relational value
- Personality speculation unless strongly grounded in specific evidence
- Claims already captured more cleanly by another candidate in this list
- Obvious logistical statements with no intelligence value ("Let's use the big conference room")
- Restatements of widely known facts ("The CFTC regulates derivatives")

Emit the surviving claims as the final output.
"""

# ═══════════════════════════════════════════════════════════════
# Output Format (shared)
# ═══════════════════════════════════════════════════════════════

OUTPUT_FORMAT = """
═══════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

Output ONLY valid JSON — no preamble, no commentary, no markdown fences:
{
  "claims": [
    {
      "id": "claim_001",
      "claim_type": "fact | position | commitment | preference | relationship | observation | tactical",
      "claim_text": "Natural language claim — one atomic statement",
      "subject_entity_id": null,
      "subject_name": "Person or entity the claim is about",
      "subject_type": "person | organization | legislation | topic",
      "target_entity": "What the claim references or null",
      "speaker": "Who said this",
      "modality": "stated | inferred | implied",
      "polarity": "positive | negative | neutral | mixed",
      "confidence": 0.0-1.0,
      "stability": "stable_fact | soft_inference | transient_observation",
      "importance": 0.0-1.0,
      "evidence_type": "quote | paraphrase | interaction_derived",
      "evidence_quote": "Exact words from transcript",
      "evidence_start": null,
      "evidence_end": null,
      "episode_id": "episode_001 or null",
      "firmness": "required | concrete | intentional | tentative | social | null (only for commitment claims)",
      "has_specific_action": "true | false | null",
      "has_deadline": "true | false | null",
      "has_condition": "true | false | null",
      "condition_text": "the contingency if present, null otherwise",
      "direction": "owed_by_me | owed_to_me | owed_by_other | mutual | null",
      "time_horizon": "ISO date | rough timeframe string | none | null",
      "due_date": "YYYY-MM-DD or null",
      "date_confidence": "exact | approximate | conditional | null_explained | null",
      "date_note": "Context for non-exact dates or null",
      "condition_trigger": "What event resolves a conditional commitment, or null",
      "recurrence": "weekly:monday | monthly:first_tuesday | null",
      "related_claim_id": "ID of paired claim, or null",
      "additional_entities": [{"name": "Full Name", "role": "co_subject | target | beneficiary"}]
    }
  ],
  "memory_writes": [
    {
      "entity_type": "person | topic | organization | self",
      "entity_id": null,
      "entity_name": "Name",
      "field": "address | kids | partner_name | city | birthday | interest | activity | life_event | emotional_context | career_history | etc",
      "value": "The factual detail",
      "source_quote": "Exact words"
    }
  ],
  "people_mentioned": [
    "Full Name of every person who performs an action, is described,
     or is referenced by name in the claims, including third parties
     mentioned in passing. Use full names where known."
  ],
  "new_contacts_mentioned": [
    {
      "name": "Full Name",
      "organization": null,
      "title": null,
      "context": "Brief context of how they were mentioned",
      "connectionTo": "Name of person who knows them (if mentioned)",
      "mentionedBy": "Speaker who mentioned them",
      "source_claim_id": "claim_xxx that triggered this mention",
      "introduced_by": "Person who introduced or referred this contact (if applicable)"
    }
  ]
}

- Extract EVERY factual detail: addresses, kids' names, partners, birthdays, hobbies, pets — even casual mentions.
- For relationship claims, subject_name is person A and target_entity is person B or org.
"""


def build_voice_claims_prompt():
    """Assemble the full voice claims extraction prompt from shared base + voice-specific parts."""
    voice_header = """You are a claims extraction system for a personal voice intelligence platform owned by Stephen Andrews.
You receive a diarized transcript segmented into topical episodes.

Your job is to extract ATOMIC CLAIMS using a three-stage internal process. Work through ALL THREE STAGES in order.
"""

    voice_specific = """
- Use timestamps from the transcript's [start-end] markers for evidence_start/end.
"""

    return (
        voice_header
        + STAGE1_CANDIDATE_DETECTION
        + STAGE2_NORMALIZATION
        + NAME_DISAMBIGUATION
        + SUBJECT_TYPE
        + ADDITIONAL_ENTITIES
        + STAGE3_FILTER
        + OUTPUT_FORMAT
        + COMMITMENT_CLASSIFICATION
        + COMMITMENT_DATE_RESOLUTION
        + voice_specific
    )


def build_text_claims_prompt():
    """Assemble the full text claims extraction prompt from shared base + text-specific parts."""
    text_header = """You are a claims extraction system for a personal text intelligence platform owned by Stephen Andrews.
You receive a formatted text message conversation and must extract ATOMIC CLAIMS.

This is TEXT (iMessage/SMS), not voice. Key differences from voice:
- Evidence references are LINE NUMBERS, not timestamps
- No vocal/audio analysis available
- Text is often compressed, abbreviated, ambiguous
- Reactions (thumbs up, heart) and shared links are meaningful signals
- Every claim MUST include an evidence_quality rating
"""

    text_evidence_quality = """
═══════════════════════════════════════════════════════════════
TEXT-SPECIFIC: EVIDENCE QUALITY
═══════════════════════════════════════════════════════════════

evidence_quality — CRITICAL for text claims:
  - explicit: Directly stated in the message. "I'll send the memo by Friday."
  - abbreviated: Likely true but expressed in compressed form. "k will do" probably means agreement.
  - ambiguous: Could go multiple ways. "sounds good" could be enthusiasm, polite deflection, or sarcasm.
  - inferred: Derived from behavioral patterns rather than explicit statements.
    Message volume changes, punctuation shifts, formality changes.
"""

    text_specific_rules = """
═══════════════════════════════════════════════════════════════
TEXT-SPECIFIC EXTRACTION RULES
═══════════════════════════════════════════════════════════════

1. Short or abbreviated messages ("k", "sounds good", thumbs up) should be assigned
   evidence_quality "abbreviated" or "ambiguous", NOT "explicit".

2. Prefer fewer high-quality claims over many speculative ones. When evidence
   is thin, mark as "inferred" rather than skipping — the review system gates it.

3. For logistical-only content (time/place coordination, simple confirmations),
   output zero claims. This is normal and expected.

4. Emotional and behavioral observations are valid from text, but ONLY when based
   on clear evidence: explicit statements ("I'm upset") or strong patterns (sudden
   formality shift from someone normally casual). NEVER infer emotional states
   from a single short message.

5. Reactions (thumbs up, heart, etc.) are meaningful signals. When a reaction references a
   specific message, note WHAT was reacted to in the claim.

6. Shared links, images, and attachments: note them as context in claims that
   reference them.

7. For relationship, observation, and tactical claims: prefer explicit evidence.
   When evidence is pattern-based, mark as evidence_quality "inferred".
"""

    text_multistatement = """
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
"""

    text_subject_linking = """
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
"""

    text_entity_recognition = """
═══════════════════════════════════════════════════════════════
ENTITY RECOGNITION
═══════════════════════════════════════════════════════════════

When a claim mentions a person or organization not in the participant roster,
note them appropriately:

- Senators, officials, public figures: use full title + name in claim text
  ("Senator Schmitt", "Senator Grassley", not just "Schmitt")
- Organizations: use full name when identifiable ("White House Office of
  Legislative Affairs", not just "WH OLA")
- First-name-only references: if the person is identifiable from context,
  flag as new_contact with available context
- Teams/groups: note as organizations when they function as entities
"""

    # Add evidence_quality to output schema note
    text_output_note = """
NOTE: For text claims, also include this field on every claim:
  "evidence_quality": "explicit | abbreviated | ambiguous | inferred"

*** people_mentioned — COMPREHENSIVE ***
Include ALL people referenced in the conversation, including:
- All conversation participants (sender and recipients)
- All third parties mentioned by name (senators, staffers, etc.)
- People referenced indirectly if identifiable
"""

    return (
        text_header
        + STAGE1_CANDIDATE_DETECTION
        + STAGE2_NORMALIZATION
        + NAME_DISAMBIGUATION
        + SUBJECT_TYPE
        + ADDITIONAL_ENTITIES
        + STAGE3_FILTER
        + OUTPUT_FORMAT
        + COMMITMENT_CLASSIFICATION
        + COMMITMENT_DATE_RESOLUTION
        + text_evidence_quality
        + text_specific_rules
        + text_multistatement
        + text_subject_linking
        + text_entity_recognition
        + text_output_note
    )
