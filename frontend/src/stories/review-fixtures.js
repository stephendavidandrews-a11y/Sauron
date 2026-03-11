/**
 * Shared deterministic fixtures for Review flow stories + future Playwright tests.
 * Every ID, timestamp, and name is stable across runs.
 */

// ── Contacts ────────────────────────────────────────────────────────────

export const contacts = [
  { id: "c-001", canonical_name: "Sarah Chen", display_name: "Sarah Chen", is_confirmed: 1 },
  { id: "c-002", canonical_name: "Mark Weber", display_name: "Mark Weber", is_confirmed: 1 },
  { id: "c-003", canonical_name: "John Smith", display_name: "John Smith", is_confirmed: 1 },
  { id: "c-004", canonical_name: "Amy Liu", display_name: "Amy Liu", is_confirmed: 1 },
  { id: "c-005", canonical_name: "David Kim", display_name: "David Kim", is_confirmed: 1 },
  { id: "c-006", canonical_name: "Stephen Andrews", display_name: "Stephen Andrews", is_confirmed: 1 },
];

// ── Claims ──────────────────────────────────────────────────────────────

let _claimId = 100;
export function makeClaim(overrides = {}) {
  const id = overrides.id ?? _claimId++;
  return {
    id,
    conversation_id: "conv-001",
    episode_id: overrides.episode_id ?? "ep-001",
    claim_type: "fact",
    claim_text: "The CFTC is expected to finalize position limits by Q3 2026.",
    confidence: 0.87,
    subject_name: "Sarah Chen",
    subject_entity_id: "c-001",
    linked_entity_name: "Sarah Chen",
    speaker_name: "Mark Weber",
    evidence_quote: "Sarah mentioned position limits will be done by end of Q3.",
    review_status: null,
    modality: "stated",
    firmness: null,
    direction: null,
    has_deadline: false,
    has_condition: false,
    has_specific_action: false,
    condition_text: null,
    time_horizon: null,
    display_overrides: null,
    entities: [
      { entity_id: "c-001", entity_name: "Sarah Chen", role: "subject", relationship_label: null },
    ],
    text_user_edited: false,
    ...overrides,
  };
}

export const claimFact = makeClaim({ id: 101 });

export const claimPosition = makeClaim({
  id: 102,
  claim_type: "position",
  claim_text: "Strongly opposes expanding swap dealer definitions to cover smaller participants.",
  confidence: 0.79,
  subject_name: "John Smith",
  subject_entity_id: "c-003",
  linked_entity_name: "John Smith",
  entities: [{ entity_id: "c-003", entity_name: "John Smith", role: "subject", relationship_label: null }],
  evidence_quote: "John was adamant that smaller firms should not fall under dealer registration.",
});

export const claimCommitment = makeClaim({
  id: 103,
  claim_type: "commitment",
  claim_text: "Will send the updated compliance framework by Friday.",
  confidence: 0.92,
  firmness: "firm",
  direction: "speaker_to_subject",
  has_deadline: true,
  has_condition: false,
  has_specific_action: true,
  time_horizon: "this_week",
  evidence_quote: "I will get that compliance framework to you by end of day Friday.",
});

export const claimRelationship = makeClaim({
  id: 104,
  claim_type: "relationship",
  claim_text: "Sarah Chen reports to Amy Liu on the enforcement team.",
  confidence: 0.65,
  subject_name: "Sarah Chen",
  subject_entity_id: "c-001",
  linked_entity_name: "Sarah Chen",
  entities: [
    { entity_id: "c-001", entity_name: "Sarah Chen", role: "subject", relationship_label: null },
    { entity_id: "c-004", entity_name: "Amy Liu", role: "object", relationship_label: "reports_to" },
  ],
});

export const claimNoEntities = makeClaim({
  id: 105,
  claim_type: "observation",
  claim_text: "The meeting ran 20 minutes over the scheduled time.",
  confidence: 0.95,
  subject_name: null,
  subject_entity_id: null,
  linked_entity_name: null,
  entities: [],
  evidence_quote: null,
});

export const claimLowConfidence = makeClaim({
  id: 106,
  claim_type: "position",
  claim_text: "Might support reducing margin requirements for end-users.",
  confidence: 0.38,
  modality: "hedged",
  evidence_quote: "I think maybe, if the conditions are right, we could look at reducing margins.",
});

export const claimEntityMismatch = makeClaim({
  id: 107,
  claim_type: "fact",
  claim_text: "The enforcement division is reviewing three pending cases.",
  subject_name: "Enforcement Division",
  subject_entity_id: "c-001",
  linked_entity_name: "Sarah Chen",
  entities: [{ entity_id: "c-001", entity_name: "Sarah Chen", role: "subject", relationship_label: null }],
  evidence_quote: "The enforcement team told me they have three cases under review.",
});

export const claimWithOverrides = makeClaim({
  id: 108,
  claim_type: "fact",
  claim_text: "My brother thinks the rulemaking will stall in committee.",
  display_overrides: [
    { start: 0, end: 10, resolved_name: "Mark Weber" },
  ],
  entities: [{ entity_id: "c-002", entity_name: "Mark Weber", role: "subject", relationship_label: "brother" }],
});

export const claimLongText = makeClaim({
  id: 109,
  claim_type: "fact",
  claim_text: "After extensive analysis of multiple data points across several conversations spanning the past quarter, the evidence strongly suggests a fundamental shift in regulatory posture from cautious incrementalism toward comprehensive market structure reform, including expanded clearing mandates, stricter position limits for speculative traders in energy and agricultural commodity derivatives markets, and harmonized cross-border reporting requirements aligned with EMIR Refit provisions.",
  confidence: 0.74,
  evidence_quote: "During the extended discussion about market structure reform, the participant elaborated at length on the complexities of cross-border derivatives regulation and the challenges of harmonizing US and EU approaches.",
});

export const claimConditionalCommitment = makeClaim({
  id: 110,
  claim_type: "commitment",
  claim_text: "Will revise the position limits proposal if the cost-benefit data supports it.",
  firmness: "tentative",
  direction: "owed_by_me",
  has_deadline: false,
  has_condition: true,
  has_specific_action: true,
  condition_text: "if cost-benefit data supports it",
  time_horizon: "none",
});

export const claimApproved = makeClaim({
  id: 115,
  review_status: "user_confirmed",
});

export const claimCorrected = makeClaim({
  id: 116,
  review_status: "user_corrected",
  claim_text: "The CFTC is expected to finalize position limits by Q4 2026.",
  text_user_edited: true,
});

export const claimDismissed = makeClaim({
  id: 117,
  review_status: "dismissed",
});

export const claimDeferred = makeClaim({
  id: 118,
  review_status: "deferred",
});

// ── Episodes ────────────────────────────────────────────────────────────

export function makeEpisode(overrides = {}) {
  return {
    id: "ep-001",
    conversation_id: "conv-001",
    episode_type: "discussion",
    title: "Position limits timeline discussion",
    summary: "Discussed the expected timeline for CFTC position limits finalization and potential impacts on market participants.",
    start_time: 45,
    end_time: 320,
    ...overrides,
  };
}

export const episodes = [
  makeEpisode({ id: "ep-001", title: "Position limits timeline discussion", episode_type: "discussion", start_time: 45, end_time: 320 }),
  makeEpisode({ id: "ep-002", title: "Swap dealer definition scope", episode_type: "negotiation", start_time: 325, end_time: 580, summary: "Negotiated scope of proposed swap dealer definition changes." }),
  makeEpisode({ id: "ep-003", title: "Compliance framework handoff", episode_type: "action_item", start_time: 585, end_time: 720, summary: "Agreed on deliverables and deadlines for the compliance framework update." }),
];

export const claimsByEpisode = {
  "ep-001": [claimFact, claimPosition, claimLowConfidence],
  "ep-002": [
    makeClaim({ id: 111, episode_id: "ep-002", claim_type: "position", claim_text: "Supports narrowing the swap dealer definition.", confidence: 0.81, subject_name: "John Smith", entities: [{ entity_id: "c-003", entity_name: "John Smith", role: "subject" }] }),
    makeClaim({ id: 112, episode_id: "ep-002", claim_type: "fact", claim_text: "The current threshold captures firms doing less than $3B notional.", confidence: 0.90, entities: [] }),
  ],
  "ep-003": [claimCommitment, claimConditionalCommitment],
};

export const orphanClaims = [
  makeClaim({ id: 120, episode_id: null, claim_type: "observation", claim_text: "Meeting started 5 minutes late due to technical issues.", confidence: 0.99, entities: [], evidence_quote: null }),
];

// Flat claims array matching episode structure
export const allClaims = [
  ...claimsByEpisode["ep-001"],
  ...claimsByEpisode["ep-002"],
  ...claimsByEpisode["ep-003"],
  ...orphanClaims,
];

// ── Transcript segments ─────────────────────────────────────────────────

export function makeSegment(overrides = {}) {
  return {
    id: overrides.id ?? 1,
    speaker_label: "SPEAKER_00",
    speaker_name: "Stephen Andrews",
    speaker_id: "c-006",
    voice_sample_count: 12,
    start_time: 0.0,
    end_time: 5.2,
    text: "Good morning, thanks for joining.",
    user_corrected: 0,
    ...overrides,
  };
}

export const transcript = [
  makeSegment({ id: 1, start_time: 0.0, end_time: 5.2, text: "Good morning, thanks for joining. Let us get started on the position limits discussion." }),
  makeSegment({ id: 2, speaker_label: "SPEAKER_01", speaker_name: "Sarah Chen", speaker_id: "c-001", voice_sample_count: 8, start_time: 5.5, end_time: 18.1, text: "Thanks Stephen. I have updates on the finalization timeline from legal." }),
  makeSegment({ id: 3, speaker_label: "SPEAKER_02", speaker_name: "Mark Weber", speaker_id: "c-002", voice_sample_count: 0, start_time: 18.5, end_time: 32.0, text: "Before we get into that, I want to flag some concerns about the swap dealer thresholds that came up in our last internal review." }),
  makeSegment({ id: 4, start_time: 32.5, end_time: 40.0, text: "Sure, go ahead Mark. We can circle back to the timeline after." }),
  makeSegment({ id: 5, speaker_label: "SPEAKER_01", speaker_name: "Sarah Chen", speaker_id: "c-001", voice_sample_count: 8, start_time: 40.5, end_time: 55.0, text: "Actually I should mention \u2014 my brother thinks the rulemaking will stall in committee given the political dynamics." }),
  makeSegment({ id: 6, speaker_label: "SPEAKER_03", speaker_name: null, speaker_id: null, voice_sample_count: 0, start_time: 55.5, end_time: 63.0, text: "I agree with that assessment. The midterm elections are going to slow everything down." }),
  makeSegment({ id: 7, speaker_label: "SPEAKER_01", speaker_name: "Sarah Chen", speaker_id: "c-001", voice_sample_count: 8, start_time: 63.5, end_time: 72.0, text: "Right, and legal confirmed that position limits should be finalized by end of Q3 at the latest." }),
  makeSegment({ id: 8, start_time: 72.5, end_time: 85.0, text: "Perfect. I will get the compliance framework to you by end of day Friday, Sarah." }),
  makeSegment({ id: 9, speaker_label: "SPEAKER_02", speaker_name: "Mark Weber", speaker_id: "c-002", voice_sample_count: 0, start_time: 85.5, end_time: 95.0, text: "One more thing \u2014 if the cost-benefit data supports it, I will revise the position limits proposal accordingly.", user_corrected: 1 }),
];

export const transcriptEmpty = [];

// ── Conversations ───────────────────────────────────────────────────────

export function makeConversation(overrides = {}) {
  return {
    id: "conv-001",
    title: "Weekly derivatives sync",
    manual_note: null,
    source: "plaud",
    captured_at: "2026-03-10T14:30:00Z",
    created_at: "2026-03-10T14:30:00Z",
    duration_seconds: 2700,
    processing_status: "completed",
    reviewed_at: null,
    context_classification: "professional",
    episode_count: 3,
    claim_count: 9,
    ...overrides,
  };
}

export const convoCompleted = makeConversation({ processing_status: "completed" });
export const convoAwaitingClaims = makeConversation({ id: "conv-002", processing_status: "awaiting_claim_review" });
export const convoAwaitingSpeakers = makeConversation({ id: "conv-003", processing_status: "awaiting_speaker_review" });
export const convoReviewed = makeConversation({ id: "conv-004", processing_status: "completed", reviewed_at: "2026-03-10T16:00:00Z" });
export const convoError = makeConversation({ id: "conv-005", processing_status: "error" });
export const convoPending = makeConversation({ id: "conv-006", processing_status: "pending" });
export const convoTriageRejected = makeConversation({ id: "conv-007", processing_status: "triage_rejected", episode_count: 0, claim_count: 0 });

// ── Synthesis / extraction ──────────────────────────────────────────────

export const synthesis = {
  summary: "Discussed CFTC position limits finalization timeline, swap dealer definition scope, and compliance framework deliverables.",
  vocal_intelligence_summary: "Speaker 00 showed confident delivery. Speaker 01 was measured and precise. Speaker 02 expressed concern with rising vocal tension.",
  word_voice_alignment: "aligned",
  topics_discussed: ["position limits", "swap dealer definitions", "compliance framework", "cost-benefit analysis"],
  follow_ups: [
    { description: "Send compliance framework to Sarah", due_date: "2026-03-14" },
    { description: "Review cost-benefit data for position limits proposal", due_date: null },
  ],
  self_coaching: [
    { observation: "Interrupted Sarah twice during the timeline discussion.", recommendation: "Practice active listening in regulatory topic transitions." },
  ],
};

export const beliefUpdates = [
  { entity_name: "Sarah Chen", belief_summary: "Position limits will be finalized by Q3 2026.", status: "active", confidence: 0.87 },
  { entity_name: "John Smith", belief_summary: "Opposes expanding swap dealer definitions.", status: "provisional", confidence: 0.79 },
];

export const reviewStats = {
  approved: 6, corrections: 2, dismissed: 1, beliefs_affected: 3,
};

// ── People review ───────────────────────────────────────────────────────

export const peopleAllGreen = [
  { original_name: "Sarah Chen", canonical_name: "Sarah Chen", entity_id: "c-001", status: "confirmed", is_self: false, is_provisional: false },
  { original_name: "Mark Weber", canonical_name: "Mark Weber", entity_id: "c-002", status: "confirmed", is_self: false, is_provisional: false },
  { original_name: "Stephen Andrews", canonical_name: "Stephen Andrews", entity_id: "c-006", status: "confirmed", is_self: true, is_provisional: false },
];

export const peopleMixed = [
  { original_name: "Stephen Andrews", canonical_name: "Stephen Andrews", entity_id: "c-006", status: "confirmed", is_self: true, is_provisional: false },
  { original_name: "Sarah Chen", canonical_name: "Sarah Chen", entity_id: "c-001", status: "confirmed", is_self: false, is_provisional: false },
  { original_name: "Mark Weber", canonical_name: "Mark Weber", entity_id: "c-002", status: "auto_resolved", is_self: false, is_provisional: false },
  { original_name: "Speaker 3", canonical_name: null, entity_id: "prov-001", status: "provisional", is_self: false, is_provisional: true },
  { original_name: "Unknown voice", canonical_name: null, entity_id: null, status: "unresolved", is_self: false, is_provisional: false },
  { original_name: "Amy Liu", canonical_name: "Amy Liu", entity_id: "c-004", status: "skipped", is_self: false, is_provisional: false },
];

export const peopleUnresolved = [
  { original_name: "Stephen Andrews", canonical_name: "Stephen Andrews", entity_id: "c-006", status: "confirmed", is_self: true, is_provisional: false },
  { original_name: "Voice A", canonical_name: null, entity_id: "prov-002", status: "provisional", is_self: false, is_provisional: true },
  { original_name: "Voice B", canonical_name: null, entity_id: null, status: "unresolved", is_self: false, is_provisional: false },
  { original_name: "Voice C", canonical_name: null, entity_id: "prov-003", status: "provisional", is_self: false, is_provisional: true },
];

// ── Relational references ───────────────────────────────────────────────

export const relationalClaims = [
  { id: 200, claim_type: "fact", claim_text: "My brother thinks the rulemaking will stall.", subject_name: "my brother", subject_entity_id: null, is_relational: true, anchor_name: "Stephen Andrews", relationship_type: "brother", entities: [], is_plural: false },
  { id: 201, claim_type: "position", claim_text: "Her boss prefers a phased implementation approach.", subject_name: "her boss", subject_entity_id: null, is_relational: true, anchor_name: "Sarah Chen", relationship_type: "boss", entities: [], is_plural: false },
];

export const relationalClaimsResolved = [
  { id: 200, claim_type: "fact", claim_text: "My brother thinks the rulemaking will stall.", subject_name: "Mark Weber", subject_entity_id: "c-002", is_relational: true, anchor_name: "Stephen Andrews", relationship_type: "brother", entities: [{ entity_id: "c-002", entity_name: "Mark Weber", role: "subject", relationship_label: "brother" }], is_plural: false },
];

// ── Linked entities map (for BulkReassignModal) ─────────────────────────

export const linkedEntities = {
  "c-001": "Sarah Chen",
  "c-002": "Mark Weber",
  "c-003": "John Smith",
  "c-006": "Stephen Andrews",
};

export const reassignPreview = {
  from_entity: "Sarah Chen", to_entity: "Amy Liu",
  claims_affected: 4, transcript_segments_affected: 3, belief_evidence_links_affected: 2,
  sample_claims: [
    { old_subject: "Sarah Chen", new_subject: "Amy Liu", claim_text: "Position limits will be finalized by Q3 2026." },
    { old_subject: "Sarah Chen", new_subject: "Amy Liu", claim_text: "Reports to Amy Liu on the enforcement team." },
  ],
};

export const reassignResult = {
  from_entity: "Sarah Chen", to_entity: "Amy Liu",
  claims_updated: 4, transcripts_updated: 3, beliefs_invalidated: 2,
  ambiguous_claims_flagged: 1, transcript_review_recommended: true,
};

// ── Queue fixture (for Review page) ─────────────────────────────────────

export const queueConversations = [
  convoAwaitingSpeakers,
  convoTriageRejected,
  convoAwaitingClaims,
  makeConversation({ id: "conv-009", processing_status: "awaiting_claim_review", title: "Quarterly budget review", duration_seconds: 3600, episode_count: 5, claim_count: 14 }),
  makeConversation({ id: "conv-008", processing_status: "extracting", title: "Morning standup", duration_seconds: 600 }),
  convoPending,
  makeConversation({ id: "conv-010", processing_status: "completed", reviewed_at: "2026-03-09T10:00:00Z", title: "Monday standup", duration_seconds: 900, episode_count: 2, claim_count: 5 }),
  makeConversation({ id: "conv-011", processing_status: "completed", reviewed_at: "2026-03-08T14:00:00Z", title: "Enforcement strategy session", duration_seconds: 5400, episode_count: 7, claim_count: 22 }),
];

export const queueCounts = {
  speaker_review: 1, triage_review: 1, claim_review: 2,
};
