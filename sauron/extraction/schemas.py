"""Extraction schemas — Pydantic models for three-pass Claude extraction (v6).

Architecture: Claims extracted directly (Sonnet). Beliefs synthesized from
claims (Opus + post-processing). Recommendations from beliefs (later phases).
These three layers MUST NOT be collapsed.

Pass 1 (Haiku 4.5): Triage + episode segmentation
Pass 2 (Sonnet 4.6): Claims extraction with evidence spans
Pass 3 (Opus 4.6): Vocal synthesis + belief updates + self-coaching
"""

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Pass 1: Haiku Triage + Episode Segmentation
# ═══════════════════════════════════════════════════════════════

class Episode(BaseModel):
    """A topical segment within a conversation."""
    title: str
    start_time: float
    end_time: float
    episode_type: str = Field(
        description="small_talk | substantive | commitment | relationship_intel | logistics | other"
    )
    summary: str


class TriageResult(BaseModel):
    """Haiku 4.5 output — triage classification + episode segmentation."""
    context_classification: str = Field(
        description="cftc_team | cftc_stakeholder | professional_network | "
                    "personal | mixed | solo_brainstorm | solo_tasks | solo_debrief | "
                    "solo_analysis | solo_reflection"
    )
    speaker_count: int
    speaker_hints: list[str] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    value_assessment: str = Field(description="high | medium | low")
    value_reasoning: str
    summary: str
    is_solo: bool = False
    solo_mode: str | None = None

    # v6 addition: episode segmentation
    episodes: list[Episode] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Pass 2: Sonnet Claims Extraction
# ═══════════════════════════════════════════════════════════════

class Claim(BaseModel):
    """An atomic, evidence-linked claim extracted from conversation."""
    id: str = Field(description="Unique claim ID (e.g., 'claim_001')")
    claim_type: str = Field(
        description="fact | position | commitment | preference | relationship | observation | tactical"
    )
    claim_text: str = Field(description="Natural language claim")
    subject_entity_id: str | None = None
    subject_name: str | None = ""
    subject_type: str = Field(
        default="person",
        description="person | organization | legislation | topic"
    )
    target_entity: str | None = None
    speaker: str | None = None
    modality: str = Field(
        default="stated",
        description="stated | inferred | implied"
    )
    polarity: str = Field(
        default="neutral",
        description="positive | negative | neutral | mixed"
    )
    confidence: float = Field(ge=0, le=1, default=0.8)
    stability: str = Field(
        default="stable_fact",
        description="stable_fact | soft_inference | transient_observation"
    )
    evidence_quote: str | None = ""
    evidence_start: float | None = None
    evidence_end: float | None = None
    review_after: str | None = None
    importance: float = Field(
        ge=0, le=1, default=0.5,
        description="0-1 provisional: does this affect future action, relationship management, or what Stephen should know?"
    )
    evidence_type: str = Field(
        default="quote",
        description="quote | paraphrase | interaction_derived"
    )
    episode_id: str | None = None

    # Text-specific: evidence quality rating (all modalities can use this)
    evidence_quality: str | None = Field(
        default=None,
        description="explicit | abbreviated | ambiguous | inferred — "
                    "how directly the claim is stated in the source material"
    )

    # Commitment classification (optional, only for claim_type='commitment')
    firmness: str | None = None  # required | concrete | intentional | tentative | social
    has_specific_action: bool | None = None
    has_deadline: bool | None = None
    has_condition: bool | None = None
    condition_text: str | None = None
    direction: str | None = None  # owed_by_me | owed_to_me | owed_by_other | mutual
    time_horizon: str | None = None  # ISO date | rough timeframe | 'none'

    # Commitment date resolution (Phase 1 text extraction)
    due_date: str | None = Field(
        default=None,
        description="YYYY-MM-DD resolved date for commitments. "
                    "Resolved from relative language using cluster timestamp."
    )
    date_confidence: str | None = Field(
        default=None,
        description="exact | approximate | conditional | null_explained — "
                    "how confident is the resolved due_date"
    )
    date_note: str | None = Field(
        default=None,
        description="Context for non-exact dates: 'after Schmitt meeting', "
                    "'pending recess schedule', 'every Monday recurring', etc."
    )
    condition_trigger: str | None = Field(
        default=None,
        description="For conditional commitments: natural language description of "
                    "what event would resolve the condition and activate the commitment"
    )
    recurrence: str | None = Field(
        default=None,
        description="Recurrence pattern if applicable: "
                    "'weekly:monday', 'monthly:first_tuesday', 'daily', etc. "
                    "due_date holds the next occurrence."
    )

    # Claim linking (pairs ask↔offer, cause↔effect, etc.)
    related_claim_id: str | None = Field(
        default=None,
        description="ID of a related claim in the same cluster "
                    "(e.g., an ask paired with its corresponding offer)"
    )

    # Multi-entity linking: additional people involved beyond subject_name
    additional_entities: list[dict] | None = Field(
        default=None,
        description="Other people involved: [{'name': 'Full Name', 'role': 'co_subject|target|beneficiary'}]"
    )


class MemoryWrite(BaseModel):
    """A structured memory update for a contact or entity."""
    entity_type: str = Field(description="person | topic | organization | self")
    entity_id: str | None = None
    entity_name: str | None = ""
    field: str = Field(
        description="address | kids | partnerName | dietaryNotes | city | birthday | "
                    "interest | activity | lifeEvent | emotionalContext | etc"
    )
    value: str
    source_quote: str | None = ""


class NewContactMention(BaseModel):
    """A structured mention of a previously unknown person."""
    name: str
    organization: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    context: str | None = None
    connectionTo: str | None = None
    mentionedBy: str | None = None
    confidence: float | None = None
    source_claim_id: str | None = None  # Cat4 Step G: ties back to originating claim
    introduced_by: str | None = None  # Cat4 Step G: provenance — who introduced this person


class ClaimsResult(BaseModel):
    """Sonnet 4.6 output — atomic claims with evidence spans."""
    claims: list[Claim] = Field(default_factory=list)
    memory_writes: list[MemoryWrite] = Field(default_factory=list)
    people_mentioned: list[str] = Field(default_factory=list)
    new_contacts_mentioned: list[NewContactMention | str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Pass 3: Opus Synthesis
# ═══════════════════════════════════════════════════════════════

class VocalInsight(BaseModel):
    """Per-speaker vocal analysis insight."""
    emotional_state: str
    rapport_assessment: str
    engagement_trend: str
    communication_style_notes: str
    topics_of_passion: list[str] = Field(default_factory=list)
    topics_of_discomfort: list[str] = Field(default_factory=list)


class BeliefUpdate(BaseModel):
    """An update to the belief layer, derived from claims."""
    entity_type: str = Field(description="person | topic | organization | relationship | self")
    entity_id: str | None = None
    entity_name: str | None = ""
    belief_key: str = Field(description="Short identifier for dedup/matching")
    belief_summary: str
    status: str = Field(
        default="provisional",
        description="active | provisional | refined | qualified | time_bounded | "
                    "superseded | contested | stale"
    )
    confidence: float = Field(ge=0, le=1, default=0.7)
    evidence_role: str = Field(
        default="support",
        description="support | contradiction | refinement | qualification"
    )
    supporting_claim_ids: list[str] = Field(default_factory=list)



class GraphEdge(BaseModel):
    from_entity: str
    from_type: str = "person"
    to_entity: str
    to_type: str = "person"
    edge_type: str
    strength: float = 0.5


class PolicyPosition(BaseModel):
    person: str
    topic: str
    position: str
    strength: float = Field(ge=0, le=1)
    notes: str | None = ""


class Commitment(BaseModel):
    description: str
    original_words: str
    resolved_date: str | None = None
    confidence: float = 0.8
    assignee: str | None = None
    direction: str = Field(
        default="i_owe",
        description="i_owe | they_owe"
    )
    source_claim_id: str | None = None


class StandingOffer(BaseModel):
    contact_name: str
    description: str
    offered_by: str
    original_words: str


class SchedulingLead(BaseModel):
    contact_name: str
    description: str
    original_words: str
    timeframe: str | None = None


class CalendarEvent(BaseModel):
    title: str
    suggested_date: str | None = None
    attendees: list[str] = Field(default_factory=list)
    original_words: str | None = ""        # Cat4 Step F: verbatim scheduling language
    start_time: str | None = ""            # Cat4 Step F: ISO datetime if extractable
    end_time: str | None = ""              # Cat4 Step F: ISO datetime if extractable
    location: str | None = ""              # Cat4 Step F: meeting location if mentioned
    is_placeholder: bool = False    # Cat4 Step F: True if time is inferred
    source_claim_id: str | None = None       # Cat4 Step F: traceable claim


class FollowUp(BaseModel):
    description: str
    priority: str = "medium"
    due_date: str | None = None


class StatusChange(BaseModel):
    """A job change, promotion, departure, relocation, or similar status update."""
    contact_name: str
    change_type: str  # "job_change", "promotion", "departure", "relocation", "title_change"
    details: str
    effective_date: str | None = None
    source_claim_id: str | None = None
    from_state: str | None = ""    # Cat4 Step C: e.g. "VP at Goldman"
    to_state: str | None = ""      # Cat4 Step C: e.g. "MD at Morgan Stanley"


class OrgIntelligence(BaseModel):
    """Organization-level intelligence: restructuring, hiring, funding, policy changes.

    intel_type includes: restructuring, hiring, funding, policy_change, acquisition,
    expansion, industry_mention, org_relationship.

    For org_relationship: related_org and relationship_type preserve the structured
    relationship. This is temporarily modeled as an OrganizationSignal in Networking;
    if org-to-org relationships become important later, they may deserve a first-class model.
    """
    organization: str
    intel_type: str  # restructuring | hiring | funding | policy_change | acquisition | expansion | industry_mention | org_relationship
    details: str
    industry: str | None = None  # for industry_mention: normalized sector label
    related_org: str | None = None  # for org_relationship: the other organization
    relationship_type: str | None = None  # for org_relationship: acquisition | partnership | subsidiary | competitor | regulator_of
    mentioned_by: str | None = None  # contact who mentioned it
    source_claim_id: str | None = None
    org_category: str | None = ""      # Cat4 Step H: industry category if discernible
    org_size: str | None = ""          # Cat4 Step H: startup, mid-market, enterprise, government_agency


class ProvenanceObservation(BaseModel):
    """How a person entered the network or how the user came to know them."""
    contact_name: str
    introduced_by: str | None = None       # name of the person who made the intro
    discovered_via: str | None = None      # "conference", "referral", "cold_outreach", "mutual_friend"
    context: str | None = ""                      # brief description of how they met/connected
    source_claim_id: str | None = None




class AffiliationMention(BaseModel):
    """A person-organization-role triple detected in conversation.

    role_type is open-ended — examples include executive, staff, consultant,
    board, advisor, partner, counsel, commissioner, chair, founder, investor,
    contractor, etc. Do NOT restrict to a closed enum.
    """
    contact_name: str
    organization: str
    title: str | None = None
    department: str | None = None
    role_type: str | None = None  # open-ended: executive, staff, consultant, board, advisor, partner, etc.
    is_current: bool = True
    change_type: str | None = None  # new_role | departure | promotion | null=static mention
    source_claim_id: str | None = None
    confidence: float = 0.7


# NOTE (Cat4 Step I): Pretexts (reasons to reach out) are a downstream derivation
# combining asks, commitments, standing_offers, scheduling_leads, and follow_ups.
# Staged for routing-layer implementation, not extracted directly by Opus.


class ReferencedResource(BaseModel):
    """A resource (book, article, tool, website, framework) mentioned in conversation."""
    resource_type: str | None = ""          # book, article, tool, website, framework, podcast, course, etc.
    title: str | None = ""
    author: str | None = ""
    url: str | None = ""
    description: str | None = ""
    mentioned_by: str | None = ""           # speaker who mentioned it
    context: str | None = ""                # why it was mentioned
    contact_name: str | None = ""           # person it's associated with (for routing)
    source_claim_id: str | None = None


class Ask(BaseModel):
    """An explicit or soft ask made during conversation."""
    ask_type: str | None = ""               # direct_ask, soft_ask, implied_need, favor, introduction_request
    description: str | None = ""
    original_words: str | None = ""
    asked_by: str | None = ""               # speaker
    asked_of: str | None = ""               # who is being asked (me, them, specific person)
    contact_name: str | None = ""           # resolved contact name for routing
    urgency: str | None = ""                # low, medium, high
    status: str | None = ""                 # open, fulfilled, declined, deferred
    source_claim_id: str | None = None


class LifeEvent(BaseModel):
    """A significant personal life event mentioned in conversation."""
    event_type: str | None = ""             # marriage, birth, death, graduation, move, retirement, health, milestone
    description: str | None = ""
    contact_name: str | None = ""           # person the event is about
    approximate_date: str | None = ""       # when it happened/will happen
    source_claim_id: str | None = None


class SynthesisResult(BaseModel):
    """Opus 4.6 output — synthesis from claims + vocal analysis."""

    # Prose synthesis
    summary: str
    relationship_notes: str | None = None
    vocal_intelligence_summary: str | None = None
    word_voice_alignment: str = "neutral"

    # Per-speaker vocal insights
    per_speaker_vocal_insights: dict[str, VocalInsight] = Field(default_factory=dict)

    # Belief updates (derived from claims, NOT extracted from transcript)
    belief_updates: list[BeliefUpdate] = Field(default_factory=list)

    # Self-coaching

    # Graph edges
    graph_edges: list[GraphEdge] = Field(default_factory=list)

    # Commitments (enriched with direction + source_claim_id)
    my_commitments: list[Commitment] = Field(default_factory=list)
    contact_commitments: list[Commitment] = Field(default_factory=list)

    # Additional extractions
    standing_offers: list[StandingOffer] = Field(default_factory=list)
    scheduling_leads: list[SchedulingLead] = Field(default_factory=list)
    calendar_events: list[CalendarEvent] = Field(default_factory=list)
    follow_ups: list[FollowUp] = Field(default_factory=list)
    policy_positions: list[PolicyPosition] = Field(default_factory=list)
    topics_discussed: list[str] = Field(default_factory=list)
    provenance_observations: list[ProvenanceObservation] = Field(default_factory=list)
    status_changes: list[StatusChange] = Field(default_factory=list)
    org_intelligence: list[OrgIntelligence] = Field(default_factory=list)
    affiliation_mentions: list[AffiliationMention] = Field(default_factory=list)

    # Cat4: New extraction objects
    referenced_resources: list[ReferencedResource] = Field(default_factory=list)
    asks: list[Ask] = Field(default_factory=list)
    life_events: list[LifeEvent] = Field(default_factory=list)

    # What changed per person
    what_changed: dict[str, str] = Field(
        default_factory=dict,
        description="contact_name -> summary of what changed since last interaction"
    )

    # Whole-conversation assessments for downstream routing
    sentiment: str | None = Field(
        default=None,
        description="warm | neutral | transactional | tense | enthusiastic"
    )
    relationship_delta: str | None = Field(
        default=None,
        description="strengthened | maintained | weakened | new"
    )

    # Context classification (confirmed/refined from triage)


# ═══════════════════════════════════════════════════════════════
# Solo Capture (simplified single-pass)
# ═══════════════════════════════════════════════════════════════

class SoloExtractionResult(BaseModel):
    """Simplified extraction for solo captures."""
    summary: str
    solo_mode: str
    tasks: list[str] = Field(default_factory=list)
    ideas: list[str] = Field(default_factory=list)
    contact_follow_ups: list[FollowUp] = Field(default_factory=list)
    strategic_insights: list[str] = Field(default_factory=list)
    journal_prose: str | None = None
    pre_meeting_goals: list[str] = Field(default_factory=list)
    linked_contact_names: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Combined result (all three passes merged for storage/routing)
# ═══════════════════════════════════════════════════════════════

class FullExtractionResult(BaseModel):
    """Combined output of all three passes for downstream consumption."""
    triage: TriageResult
    claims: ClaimsResult
    synthesis: SynthesisResult
