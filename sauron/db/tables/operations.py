"""Operational tables: performance, retention, intentions, review policy, annotations."""

OPERATIONS_SQL = """
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

CREATE INDEX IF NOT EXISTS idx_personal_performance_date ON personal_performance(date);

CREATE TABLE IF NOT EXISTS retention_log (
    id TEXT PRIMARY KEY,
    audio_file_id TEXT,
    action TEXT,
    performed_at DATETIME DEFAULT (datetime('now'))
);

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

CREATE INDEX IF NOT EXISTS idx_meeting_intentions_contact ON meeting_intentions(target_contact_id);

CREATE INDEX IF NOT EXISTS idx_meeting_intentions_conversation ON meeting_intentions(conversation_id);

CREATE TABLE IF NOT EXISTS review_policy_rules (
    id TEXT PRIMARY KEY,
    modality TEXT NOT NULL,
    claim_type TEXT,
    condition_json TEXT,
    tier TEXT NOT NULL,
    rationale TEXT,
    priority INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT (datetime('now'))
);

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

CREATE INDEX IF NOT EXISTS idx_transcript_annotations_conversation
    ON transcript_annotations(conversation_id);

CREATE INDEX IF NOT EXISTS idx_transcript_annotations_segment
    ON transcript_annotations(transcript_segment_id);

CREATE TABLE IF NOT EXISTS condition_matches (
    id TEXT PRIMARY KEY,
    conditional_claim_id TEXT NOT NULL,
    matching_claim_id TEXT NOT NULL,
    matching_conversation_id TEXT,
    similarity REAL NOT NULL,
    condition_trigger TEXT,
    matching_claim_text TEXT,
    status TEXT DEFAULT 'pending',
    resolved_due_date TEXT,
    reviewer_notes TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    FOREIGN KEY (conditional_claim_id) REFERENCES event_claims(id),
    FOREIGN KEY (matching_claim_id) REFERENCES event_claims(id)
);

CREATE INDEX IF NOT EXISTS idx_condition_matches_status ON condition_matches(status);

CREATE TABLE IF NOT EXISTS merge_audit_log (
    id TEXT PRIMARY KEY,
    networking_app_contact_id TEXT NOT NULL,
    keeper_id TEXT NOT NULL,
    keeper_name TEXT,
    removed_ids TEXT,
    removed_names TEXT,
    fields_merged TEXT,
    fk_updates TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);
"""
