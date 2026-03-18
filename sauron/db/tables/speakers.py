"""Speaker identification and contact tables."""

SPEAKERS_SQL = """
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

CREATE INDEX IF NOT EXISTS idx_vocal_features_conversation ON vocal_features(conversation_id);

CREATE INDEX IF NOT EXISTS idx_vocal_features_speaker ON vocal_features(speaker_id);

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

CREATE INDEX IF NOT EXISTS idx_vocal_baselines_contact ON vocal_baselines(contact_id);

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
    is_primary BOOLEAN DEFAULT 0,
    synced_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cac_org ON contact_affiliations_cache(networking_org_id);

CREATE INDEX IF NOT EXISTS idx_cac_contact ON contact_affiliations_cache(unified_contact_id);

CREATE INDEX IF NOT EXISTS idx_cac_org_name ON contact_affiliations_cache(org_name);

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

CREATE INDEX IF NOT EXISTS idx_voice_profiles_contact ON voice_profiles(contact_id);

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
    source_conversation_id TEXT,
    current_title TEXT,
    current_organization TEXT,
    title TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_unified_contacts_cftc_team ON unified_contacts(cftc_team_member_id);

CREATE INDEX IF NOT EXISTS idx_unified_contacts_networking ON unified_contacts(networking_app_contact_id);

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
"""
