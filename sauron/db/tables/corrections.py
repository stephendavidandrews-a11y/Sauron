"""Corrections, learning, and search telemetry tables."""

CORRECTIONS_SQL = """
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

CREATE TABLE IF NOT EXISTS prompt_amendments (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    amendment_text TEXT NOT NULL,
    source_analysis TEXT,
    correction_count INTEGER,
    active BOOLEAN DEFAULT TRUE,
    target_pass TEXT DEFAULT 'claims',
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prompt_amendments_active ON prompt_amendments(active);

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

CREATE INDEX IF NOT EXISTS idx_contact_prefs_contact ON contact_extraction_preferences(contact_id);

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
