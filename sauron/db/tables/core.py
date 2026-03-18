"""Core processing tables: conversations, audio_files, transcripts, extractions."""

CORE_SQL = """
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
    modality TEXT DEFAULT 'voice',
    current_stage TEXT DEFAULT 'ingest',
    stage_detail TEXT,
    run_status TEXT DEFAULT 'active',
    blocking_reason TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_conversations_modality ON conversations(modality);

CREATE INDEX IF NOT EXISTS idx_conversations_captured ON conversations(captured_at);

CREATE INDEX IF NOT EXISTS idx_conversations_run_status ON conversations(run_status);

CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(processing_status);

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

CREATE INDEX IF NOT EXISTS idx_audio_files_conversation ON audio_files(conversation_id);

CREATE INDEX IF NOT EXISTS idx_audio_files_tier ON audio_files(storage_tier);

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

CREATE INDEX IF NOT EXISTS idx_transcripts_speaker ON transcripts(speaker_id);

CREATE INDEX IF NOT EXISTS idx_transcripts_conversation ON transcripts(conversation_id);

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

CREATE INDEX IF NOT EXISTS idx_extractions_conversation ON extractions(conversation_id);
"""
