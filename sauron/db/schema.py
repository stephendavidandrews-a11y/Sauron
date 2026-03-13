"""Full sauron.db schema — all tables from the design plan (v5)."""

import logging
import sqlite3
from pathlib import Path

from sauron.config import DB_PATH

logger = logging.getLogger(__name__)


SCHEMA_SQL = """
-- Core Processing

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    captured_at DATETIME NOT NULL,
    duration_seconds REAL,
    calendar_event_id TEXT,
    context_classification TEXT,
    processing_status TEXT DEFAULT 'pending',
    processed_at DATETIME,
    audio_file_id TEXT,
    manual_note TEXT,
    title TEXT,
    flagged_for_review BOOLEAN DEFAULT 0,
    reviewed_at DATETIME,
    routed_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audio_files (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    original_path TEXT NOT NULL,
    current_path TEXT NOT NULL,
    storage_tier TEXT DEFAULT 'hot',
    file_size_bytes INTEGER,
    format TEXT,
    duration_seconds REAL,
    checksum TEXT,
    compressed_path TEXT,
    moved_to_cold_at DATETIME,
    deleted_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transcripts (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    speaker_id TEXT,
    speaker_label TEXT,
    start_time REAL,
    end_time REAL,
    text TEXT,
    word_timestamps TEXT,
    original_text TEXT,
    user_corrected BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extractions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    pass_number INTEGER DEFAULT 1,
    extraction_json TEXT,
    extraction_version TEXT,
    model_used TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Vocal Analysis

CREATE TABLE IF NOT EXISTS vocal_features (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    speaker_id TEXT,
    segment_start REAL,
    segment_end REAL,
    pitch_mean REAL,
    pitch_std REAL,
    pitch_min REAL,
    pitch_max REAL,
    jitter REAL,
    shimmer REAL,
    hnr REAL,
    intensity_mean REAL,
    f1_mean REAL,
    f2_mean REAL,
    f3_mean REAL,
    mfcc_means TEXT,
    rms_mean REAL,
    spectral_centroid REAL,
    zcr_mean REAL,
    spectral_rolloff REAL,
    speaking_rate_wpm REAL,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vocal_baselines (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    pitch_mean REAL,
    pitch_std REAL,
    jitter REAL,
    shimmer REAL,
    hnr REAL,
    speaking_rate_wpm REAL,
    spectral_centroid REAL,
    rms_mean REAL,
    f1_mean REAL,
    f2_mean REAL,
    f3_mean REAL,
    sample_count INTEGER DEFAULT 0,
    last_updated DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Speaker Identification


-- Wave 2: Affiliation cache (mirror of Networking App state)
CREATE TABLE IF NOT EXISTS contact_affiliations_cache (
    id TEXT PRIMARY KEY,
    unified_contact_id TEXT NOT NULL REFERENCES unified_contacts(id),
    networking_affiliation_id TEXT NOT NULL UNIQUE,
    networking_org_id TEXT NOT NULL,
    org_name TEXT NOT NULL,
    org_industry TEXT,
    title TEXT,
    department TEXT,
    role_type TEXT,
    is_current BOOLEAN DEFAULT 1,
    start_date TEXT,
    end_date TEXT,
    resolution_source TEXT,
    synced_at DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cac_contact ON contact_affiliations_cache(unified_contact_id);
CREATE INDEX IF NOT EXISTS idx_cac_org ON contact_affiliations_cache(networking_org_id);
CREATE INDEX IF NOT EXISTS idx_cac_org_name ON contact_affiliations_cache(org_name);

-- Wave 3: provisional org suggestions for review
CREATE TABLE IF NOT EXISTS provisional_org_suggestions (
    id TEXT PRIMARY KEY,
    raw_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    conversation_id TEXT REFERENCES conversations(id),
    source_context TEXT,
    resolution_source_context TEXT,
    status TEXT DEFAULT 'pending',
    resolved_org_id TEXT,
    resolved_metadata TEXT,
    suggested_by TEXT,
    created_at DATETIME DEFAULT (datetime('now')),
    resolved_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_prov_org_status ON provisional_org_suggestions(status);
CREATE INDEX IF NOT EXISTS idx_prov_org_normalized ON provisional_org_suggestions(normalized_name);

CREATE TABLE IF NOT EXISTS voice_profiles (
    id TEXT PRIMARY KEY,
    contact_id TEXT,
    display_name TEXT NOT NULL,
    mean_embedding BLOB NOT NULL,
    sample_count INTEGER DEFAULT 0,
    confidence_score REAL DEFAULT 0.0,
    best_sample_snr REAL,
    created_at DATETIME DEFAULT (datetime('now')),
    updated_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS unified_contacts (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    networking_app_contact_id TEXT,
    cftc_team_member_id INTEGER,
    cftc_stakeholder_id INTEGER,
    voice_profile_id TEXT REFERENCES voice_profiles(id),
    phone_number TEXT,
    email TEXT,
    calendar_aliases TEXT,
    aliases TEXT,
    relationships TEXT,
    is_confirmed BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS voice_samples (
    id TEXT PRIMARY KEY,
    voice_profile_id TEXT REFERENCES voice_profiles(id),
    embedding BLOB NOT NULL,
    source_conversation_id TEXT REFERENCES conversations(id),
    source_type TEXT,
    confirmation_method TEXT,
    speaker_label TEXT,
    duration_seconds REAL,
    signal_to_noise REAL,
    is_clean_segment BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS voice_match_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    speaker_label TEXT,
    matched_profile_id TEXT REFERENCES voice_profiles(id),
    similarity_score REAL,
    match_method TEXT,
    was_correct BOOLEAN,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Corrections

CREATE TABLE IF NOT EXISTS extraction_corrections (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    correction_type TEXT,
    original_value TEXT,
    corrected_value TEXT,
    corrected_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS correction_events (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    episode_id TEXT,
    claim_id TEXT,
    belief_id TEXT,
    error_type TEXT,
    old_value TEXT,
    new_value TEXT,
    user_feedback TEXT,
    correction_source TEXT DEFAULT 'manual_ui',
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ce_error_type ON correction_events(error_type);
CREATE INDEX IF NOT EXISTS idx_ce_conversation ON correction_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_ce_created ON correction_events(created_at);

CREATE TABLE IF NOT EXISTS vocal_overrides (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    speaker_id TEXT,
    override_reason TEXT,
    note TEXT,
    exclude_from_baseline BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Knowledge Graph

CREATE TABLE IF NOT EXISTS graph_edges (
    id TEXT PRIMARY KEY,
    from_entity TEXT NOT NULL,
    from_type TEXT NOT NULL,
    to_entity TEXT NOT NULL,
    to_type TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    strength REAL DEFAULT 0.5,
    source_conversation_id TEXT,
    observed_at DATETIME,
    expires_at DATETIME,
    superseded_by TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Policy Positions

CREATE TABLE IF NOT EXISTS policy_positions (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    position TEXT NOT NULL,
    strength REAL,
    source_conversation_id TEXT REFERENCES conversations(id),
    observed_at DATETIME,
    superseded_at DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Personal Performance (v5 expanded)

CREATE TABLE IF NOT EXISTS personal_performance (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    date TEXT NOT NULL,
    time_of_day TEXT,
    day_of_week TEXT,
    meetings_prior_today INTEGER,
    context_classification TEXT,
    counterpart_seniority TEXT,
    participant_count INTEGER,
    was_planned BOOLEAN,
    pitch_mean REAL,
    pitch_std REAL,
    jitter REAL,
    shimmer REAL,
    hnr REAL,
    speaking_rate_wpm REAL,
    energy_mean REAL,
    spectral_centroid REAL,
    jitter_vs_baseline REAL,
    pitch_std_vs_baseline REAL,
    hnr_vs_baseline REAL,
    energy_vs_baseline REAL,
    talk_time_ratio REAL,
    question_count INTEGER,
    statement_to_question_ratio REAL,
    interruption_count_by_you INTEGER,
    interruption_count_of_you INTEGER,
    avg_response_latency_ms REAL,
    longest_monologue_seconds REAL,
    goal_achieved TEXT,
    goal_assessment_source TEXT,
    outcome_notes TEXT,
    coaching_observations TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Retention Management

CREATE TABLE IF NOT EXISTS retention_log (
    id TEXT PRIMARY KEY,
    audio_file_id TEXT,
    action TEXT,
    performed_at DATETIME DEFAULT (datetime('now'))
);

-- Meeting Intentions (prep -> conversation -> debrief feedback loop)

CREATE TABLE IF NOT EXISTS meeting_intentions (
    id TEXT PRIMARY KEY,
    target_contact_id TEXT,
    conversation_id TEXT REFERENCES conversations(id),
    debrief_conversation_id TEXT REFERENCES conversations(id),
    goals TEXT,
    concerns TEXT,
    strategy TEXT,
    auto_brief TEXT,
    captured_at DATETIME,
    goals_achieved TEXT,
    outcome_notes TEXT,
    unexpected_outcomes TEXT,
    assessed_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Iterative Learning - Prompt Amendments

CREATE TABLE IF NOT EXISTS prompt_amendments (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    amendment_text TEXT NOT NULL,
    source_analysis TEXT,
    correction_count INTEGER,
    active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Per-contact extraction preferences

CREATE TABLE IF NOT EXISTS contact_extraction_preferences (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    commitment_confidence_threshold REAL,
    typical_follow_through_rate REAL,
    extraction_depth TEXT,
    vocal_alert_sensitivity TEXT,
    relationship_importance REAL,
    custom_notes TEXT,
    last_updated DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Semantic Search Embeddings

CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    conversation_id TEXT REFERENCES conversations(id),
    contact_id TEXT,
    text_content TEXT NOT NULL,
    embedding BLOB NOT NULL,
    created_at DATETIME DEFAULT (datetime('now'))
);


-- ═══ V6: Claims-First Architecture ═══

CREATE TABLE IF NOT EXISTS event_episodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    title TEXT,
    episode_type TEXT,
    start_time REAL,
    end_time REAL,
    summary TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS event_claims (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    episode_id TEXT REFERENCES event_episodes(id),
    claim_type TEXT,
    claim_text TEXT NOT NULL,
    subject_entity_id TEXT,
    subject_name TEXT,
    target_entity TEXT,
    speaker_id TEXT,
    modality TEXT,
    polarity TEXT,
    confidence REAL,
    stability TEXT,
    evidence_quote TEXT,
    evidence_start REAL,
    evidence_end REAL,
    review_after DATETIME,
    importance REAL,
    evidence_type TEXT,
    display_overrides TEXT,
    review_status TEXT,
    firmness TEXT,
    has_specific_action BOOLEAN,
    has_deadline BOOLEAN,
    has_condition BOOLEAN,
    condition_text TEXT,
    direction TEXT,
    time_horizon TEXT,
    text_user_edited BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS claim_entities (
    id TEXT PRIMARY KEY,
    claim_id TEXT REFERENCES event_claims(id) ON DELETE CASCADE,
    entity_id TEXT REFERENCES unified_contacts(id),
    entity_name TEXT,
    role TEXT DEFAULT 'subject',
    confidence REAL,
    link_source TEXT DEFAULT 'model',
    created_at DATETIME DEFAULT (datetime('now')),
    UNIQUE(claim_id, entity_id, role)
);

CREATE INDEX IF NOT EXISTS idx_claim_entities_claim ON claim_entities(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_entities_entity ON claim_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_entities_source ON claim_entities(link_source);

CREATE TABLE IF NOT EXISTS beliefs (
    id TEXT PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    belief_key TEXT,
    belief_summary TEXT,
    status TEXT DEFAULT 'provisional',
    confidence REAL,
    support_count INTEGER DEFAULT 0,
    contradiction_count INTEGER DEFAULT 0,
    first_observed_at DATETIME,
    last_confirmed_at DATETIME,
    last_changed_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS belief_evidence (
    id TEXT PRIMARY KEY,
    belief_id TEXT REFERENCES beliefs(id),
    claim_id TEXT REFERENCES event_claims(id),
    weight REAL,
    evidence_role TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS what_changed_snapshots (
    id TEXT PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    snapshot_date DATETIME,
    change_summary TEXT,
    old_state_json TEXT,
    new_state_json TEXT,
    significance REAL,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- DEPRECATED (Step I): Zero data, zero writers. Kept for backward compat.
CREATE TABLE IF NOT EXISTS opportunity_signals (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    target_contact_id TEXT,
    signal_type TEXT,
    priority TEXT,
    explanation TEXT,
    recommended_action TEXT,
    status TEXT DEFAULT 'open',
    created_at DATETIME DEFAULT (datetime('now'))
);

-- DEPRECATED (Step I): Zero data, zero writers. Kept for backward compat.
CREATE TABLE IF NOT EXISTS ask_vectors (
    id TEXT PRIMARY KEY,
    target_contact_id TEXT,
    conversation_id TEXT REFERENCES conversations(id),
    preferred_channel TEXT,
    framing_notes TEXT,
    reciprocity_angle TEXT,
    avoid_notes TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Indexes (original)

CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(processing_status);
CREATE INDEX IF NOT EXISTS idx_conversations_captured ON conversations(captured_at);
CREATE INDEX IF NOT EXISTS idx_transcripts_conversation ON transcripts(conversation_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_speaker ON transcripts(speaker_id);
CREATE INDEX IF NOT EXISTS idx_vocal_features_conversation ON vocal_features(conversation_id);
CREATE INDEX IF NOT EXISTS idx_vocal_features_speaker ON vocal_features(speaker_id);
CREATE INDEX IF NOT EXISTS idx_vocal_baselines_contact ON vocal_baselines(contact_id);
CREATE INDEX IF NOT EXISTS idx_voice_profiles_contact ON voice_profiles(contact_id);
CREATE INDEX IF NOT EXISTS idx_unified_contacts_networking ON unified_contacts(networking_app_contact_id);
CREATE INDEX IF NOT EXISTS idx_unified_contacts_cftc_team ON unified_contacts(cftc_team_member_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_from ON graph_edges(from_entity, from_type);
CREATE INDEX IF NOT EXISTS idx_graph_edges_to ON graph_edges(to_entity, to_type);
CREATE INDEX IF NOT EXISTS idx_graph_edges_type ON graph_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_extractions_conversation ON extractions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_audio_files_conversation ON audio_files(conversation_id);
CREATE INDEX IF NOT EXISTS idx_audio_files_tier ON audio_files(storage_tier);
CREATE INDEX IF NOT EXISTS idx_policy_positions_contact ON policy_positions(contact_id);
CREATE INDEX IF NOT EXISTS idx_personal_performance_date ON personal_performance(date);

-- Indexes (v5 additions)

CREATE INDEX IF NOT EXISTS idx_meeting_intentions_contact ON meeting_intentions(target_contact_id);
CREATE INDEX IF NOT EXISTS idx_meeting_intentions_conversation ON meeting_intentions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_prompt_amendments_active ON prompt_amendments(active);
CREATE INDEX IF NOT EXISTS idx_contact_prefs_contact ON contact_extraction_preferences(contact_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_conversation ON embeddings(conversation_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_contact ON embeddings(contact_id);

-- Indexes (v6 additions)

CREATE INDEX IF NOT EXISTS idx_event_episodes_conversation ON event_episodes(conversation_id);
CREATE INDEX IF NOT EXISTS idx_event_episodes_type ON event_episodes(episode_type);
CREATE INDEX IF NOT EXISTS idx_event_claims_conversation ON event_claims(conversation_id);
CREATE INDEX IF NOT EXISTS idx_event_claims_episode ON event_claims(episode_id);
CREATE INDEX IF NOT EXISTS idx_event_claims_type ON event_claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_event_claims_speaker ON event_claims(speaker_id);
CREATE INDEX IF NOT EXISTS idx_event_claims_subject ON event_claims(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_beliefs_entity ON beliefs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_beliefs_key ON beliefs(belief_key);
CREATE INDEX IF NOT EXISTS idx_beliefs_status ON beliefs(status);
CREATE INDEX IF NOT EXISTS idx_belief_evidence_belief ON belief_evidence(belief_id);
CREATE INDEX IF NOT EXISTS idx_belief_evidence_claim ON belief_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_what_changed_entity ON what_changed_snapshots(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_what_changed_date ON what_changed_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_opportunity_signals_contact ON opportunity_signals(target_contact_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_signals_status ON opportunity_signals(status);
CREATE INDEX IF NOT EXISTS idx_ask_vectors_contact ON ask_vectors(target_contact_id);

-- Belief transitions (tracks every status change for movement visualization)
CREATE TABLE IF NOT EXISTS belief_transitions (
    id TEXT PRIMARY KEY,
    belief_id TEXT REFERENCES beliefs(id),
    old_status TEXT,
    new_status TEXT,
    driver TEXT,
    source_conversation_id TEXT,
    source_correction_id TEXT,
    cause_summary TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_belief_transitions_belief
    ON belief_transitions(belief_id);
CREATE INDEX IF NOT EXISTS idx_belief_transitions_created
    ON belief_transitions(created_at);

-- Search telemetry (v13)
CREATE TABLE IF NOT EXISTS search_events (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    query_type TEXT,
    sections_returned TEXT,
    result_count INTEGER,
    result_clicked TEXT,
    time_to_click_ms INTEGER,
    reformulated BOOLEAN DEFAULT 0,
    session_id TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_search_events_created ON search_events(created_at);
CREATE INDEX IF NOT EXISTS idx_search_events_query ON search_events(query);

-- Belief re-synthesis proposals (v14)
CREATE TABLE IF NOT EXISTS belief_resynthesis_proposals (
    id TEXT PRIMARY KEY,
    belief_id TEXT REFERENCES beliefs(id),
    trigger_correction_id TEXT,
    current_summary TEXT,
    current_status TEXT,
    proposed_summary TEXT,
    proposed_status TEXT,
    proposed_confidence REAL,
    reasoning TEXT,
    status TEXT DEFAULT 'pending',
    resolved_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_resynth_belief ON belief_resynthesis_proposals(belief_id);
CREATE INDEX IF NOT EXISTS idx_resynth_status ON belief_resynthesis_proposals(status);

-- Amendment effectiveness tracking (v14)
CREATE TABLE IF NOT EXISTS amendment_effectiveness (
    id TEXT PRIMARY KEY,
    amendment_id TEXT REFERENCES prompt_amendments(id),
    amendment_version TEXT,
    error_type TEXT,
    corrections_before INTEGER,
    corrections_after INTEGER,
    period_days INTEGER,
    effectiveness TEXT,
    computed_at DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_amend_eff_amendment ON amendment_effectiveness(amendment_id);

-- Reprocessing comparisons (v14)
CREATE TABLE IF NOT EXISTS reprocessing_comparisons (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    old_extraction_id TEXT,
    new_extraction_id TEXT,
    amendment_version TEXT,
    claims_reproduced INTEGER,
    claims_missed INTEGER,
    claims_new INTEGER,
    corrections_resolved INTEGER,
    corrections_regressed INTEGER,
    comparison_json TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reprocess_conversation ON reprocessing_comparisons(conversation_id);


"""


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialize the sauron.db database with full schema and run migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    conn.executescript(ROUTING_LOG_SQL)
    conn.executescript(SYNTHESIS_ENTITY_LINKS_SQL)
    conn.executescript(ROUTING_SUMMARIES_SQL)
    conn.close()
    logger.info("[MIGRATION] Schema tables created/verified at %s", db_path)

    # Run migrations for existing DBs that may be behind current schema
    from sauron.db.migrate import run_migration
    run_migration(db_path)

    # Post-migration verification: confirm critical columns exist
    _verify_schema(db_path)


def _verify_schema(db_path: Path = DB_PATH) -> None:
    """Post-migration check: verify critical columns exist."""
    critical_columns = [
        ("graph_edges", "from_type"),
        ("graph_edges", "to_type"),
        ("graph_edges", "review_status"),
        ("routing_summaries", "conversation_id"),
        ("routing_summaries", "final_state"),
        ("event_claims", "review_status"),
        ("event_claims", "text_user_edited"),
        ("unified_contacts", "networking_app_contact_id"),
        ("unified_contacts", "relationships"),
        ("unified_contacts", "current_title"),
        ("unified_contacts", "current_organization"),
        ("conversations", "reviewed_at"),
        ("conversations", "routed_at"),
        ("transcripts", "original_text"),
        ("transcripts", "user_corrected"),
    ]
    conn = sqlite3.connect(str(db_path), timeout=30)
    missing = []
    for table, column in critical_columns:
        try:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            if column not in columns:
                missing.append(f"{table}.{column}")
        except Exception:
            missing.append(f"{table}.{column} (table missing)")
    conn.close()

    if missing:
        logger.error(
            "[MIGRATION] SCHEMA VERIFICATION FAILED — missing columns: %s",
            ", ".join(missing),
        )
    else:
        logger.info(
            "[MIGRATION] Schema verification passed — %d critical columns confirmed",
            len(critical_columns),
        )


def migrate_db(db_path: Path = DB_PATH) -> None:
    """Run migrations on an existing database to bring it to v5 schema.

    Safe to run multiple times (all operations are idempotent).
    For fresh databases, use init_db() instead.
    
-- transcript_annotations (v10 -- pipeline redesign)

CREATE TABLE IF NOT EXISTS transcript_annotations (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    transcript_segment_id TEXT REFERENCES transcripts(id),
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    original_text TEXT NOT NULL,
    resolved_contact_id TEXT REFERENCES unified_contacts(id),
    resolved_name TEXT NOT NULL,
    annotation_type TEXT DEFAULT 'name',
    created_at DATETIME DEFAULT (datetime('now'))
);

-- Indexes (v10 additions)

CREATE INDEX IF NOT EXISTS idx_transcript_annotations_conversation
    ON transcript_annotations(conversation_id);
CREATE INDEX IF NOT EXISTS idx_transcript_annotations_segment
    ON transcript_annotations(transcript_segment_id);

"""
    from sauron.db.migrate import run_migration
    run_migration(db_path)


if __name__ == "__main__":
    init_db()


# ── V18: Routing summaries (degraded-state visibility) ──────

ROUTING_SUMMARIES_SQL = """
CREATE TABLE IF NOT EXISTS routing_summaries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    routing_attempt_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    final_state TEXT NOT NULL,
    core_lanes TEXT NOT NULL,
    secondary_lanes TEXT NOT NULL,
    pending_entities TEXT,
    warning_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
CREATE INDEX IF NOT EXISTS idx_rs_conversation ON routing_summaries(conversation_id);
CREATE INDEX IF NOT EXISTS idx_rs_state ON routing_summaries(final_state);
"""

# ── V15: Routing log (Sauron ↔ Networking integration) ──────────

# Appended to SCHEMA_SQL via migration; included here for fresh installs
ROUTING_LOG_SQL = """
CREATE TABLE IF NOT EXISTS routing_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    target_system TEXT NOT NULL,
    route_type TEXT NOT NULL DEFAULT 'direct_write',
    object_class TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    entity_id TEXT,
    attempts INTEGER DEFAULT 0,
    last_attempt_at DATETIME,
    last_error TEXT,
    payload_json TEXT,
    networking_item_id TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_routing_log_conversation ON routing_log(conversation_id);
CREATE INDEX IF NOT EXISTS idx_routing_log_status ON routing_log(status);
CREATE INDEX IF NOT EXISTS idx_routing_log_entity ON routing_log(entity_id);
CREATE INDEX IF NOT EXISTS idx_routing_log_target ON routing_log(target_system);
"""


# ── V16: Synthesis entity links (Entity Resolution Phase 1) ─────

SYNTHESIS_ENTITY_LINKS_SQL = """
CREATE TABLE IF NOT EXISTS synthesis_entity_links (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    object_type TEXT NOT NULL,
    object_index INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    original_name TEXT NOT NULL,
    resolved_entity_id TEXT,
    resolution_method TEXT,
    confidence REAL,
    link_source TEXT DEFAULT 'auto_synthesis',
    created_at DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sel_conversation ON synthesis_entity_links(conversation_id);
CREATE INDEX IF NOT EXISTS idx_sel_entity ON synthesis_entity_links(resolved_entity_id);

CREATE TABLE IF NOT EXISTS pending_object_routes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    route_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    blocked_on_entity TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    released_at TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
CREATE INDEX IF NOT EXISTS idx_pending_routes_entity ON pending_object_routes(blocked_on_entity);
CREATE INDEX IF NOT EXISTS idx_pending_routes_status ON pending_object_routes(released_at);
"""
