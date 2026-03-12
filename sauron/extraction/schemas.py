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
    subject_name: str = ""
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
    evidence_quote: str = ""
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

    # Commitment classification (optional, only for claim_type='commitment')
    firmness: str | None = None  # concrete | intentional | tentative | social
    has_specific_action: bool | None = None
    has_deadline: bool | None = None
    has_condition: bool | None = None
    condition_text: str | None = None
    direction: str | None = None  # owed_by_me | owed_to_me | owed_by_other | mutual
    time_horizon: str | None = None  # ISO date | rough timeframe | 'none'


class MemoryWrite(BaseModel):
    """A structured memory update for a contact or entity."""
    entity_type: str = Field(description="person | topic | organization | self")
    entity_id: str | None = None
    entity_name: str = ""
    field: str = Field(
        description="address | kids | partnerName | dietaryNotes | city | birthday | "
                    "interest | activity | lifeEvent | emotionalContext | etc"
    )
    value: str
    source_quote: str = ""


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


class ClaimsResult(BaseModel):
    """Sonnet 4.6 output — atomic claims with evidence spans."""
    claims: list[Claim] = Field(default_factory=list)
    memory_writes: list[MemoryWrite] = Field(default_factory=list)
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
    entity_name: str = ""
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


class SelfCoaching(BaseModel):
    observation: str
    recommendation: str | None = None


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
    notes: str = ""


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


class OrgIntelligence(BaseModel):
    """Organization-level intelligence: restructuring, hiring, funding, policy changes."""
    organization: str
    intel_type: str  # "restructuring", "hiring", "funding", "policy_change", "acquisition", "expansion"
    details: str
    mentioned_by: str | None = None  # contact who mentioned it
    source_claim_id: str | None = None


class ProvenanceObservation(BaseModel):
    """How a person entered the network or how the user came to know them."""
    contact_name: str
    introduced_by: str | None = None       # name of the person who made the intro
    discovered_via: str | None = None      # "conference", "referral", "cold_outreach", "mutual_friend"
    context: str = ""                      # brief description of how they met/connected
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
    self_coaching: list[SelfCoaching] = Field(default_factory=list)

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
    context_classification: str = "mixed"


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
