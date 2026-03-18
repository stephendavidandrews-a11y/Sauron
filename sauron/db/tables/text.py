"""Text ingestion tables: threads, messages, clusters, sync state, pending contacts."""

TEXT_SQL = """
CREATE TABLE IF NOT EXISTS text_threads (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    thread_identifier TEXT NOT NULL,
    thread_type TEXT NOT NULL,
    display_name TEXT,
    participant_phones TEXT,
    participant_contact_ids TEXT,
    first_message_at DATETIME,
    last_message_at DATETIME,
    is_active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT (datetime('now')),
    UNIQUE(source, thread_identifier)
);

CREATE TABLE IF NOT EXISTS text_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES text_threads(id),
    source_message_id TEXT,
    sender_phone TEXT,
    sender_contact_id TEXT,
    direction TEXT NOT NULL,
    content TEXT,
    content_type TEXT DEFAULT 'text',
    timestamp DATETIME NOT NULL,
    is_group_message INTEGER DEFAULT 0,
    attachment_type TEXT,
    attachment_filename TEXT,
    attachment_url TEXT,
    refers_to_message_id TEXT,
    is_from_me INTEGER,
    raw_metadata TEXT,
    created_at DATETIME DEFAULT (datetime('now')),
    UNIQUE(thread_id, source_message_id)
);

CREATE INDEX IF NOT EXISTS idx_tm_sender ON text_messages(sender_contact_id);

CREATE INDEX IF NOT EXISTS idx_tm_thread ON text_messages(thread_id);

CREATE INDEX IF NOT EXISTS idx_tm_timestamp ON text_messages(timestamp);

CREATE TABLE IF NOT EXISTS text_clusters (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES text_threads(id),
    conversation_id TEXT REFERENCES conversations(id),
    cluster_method TEXT DEFAULT 'overnight_split',
    depth_lane INTEGER,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    message_count INTEGER,
    participant_count INTEGER,
    merged_from TEXT,
    split_from TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tc_thread ON text_clusters(thread_id);

CREATE INDEX IF NOT EXISTS idx_tc_conversation ON text_clusters(conversation_id);

CREATE TABLE IF NOT EXISTS text_cluster_messages (
    cluster_id TEXT NOT NULL REFERENCES text_clusters(id),
    message_id TEXT NOT NULL REFERENCES text_messages(id),
    ordinal INTEGER NOT NULL,
    PRIMARY KEY (cluster_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_tcm_message ON text_cluster_messages(message_id);

CREATE INDEX IF NOT EXISTS idx_tcm_cluster ON text_cluster_messages(cluster_id);

CREATE TABLE IF NOT EXISTS text_sync_state (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL UNIQUE,
    last_sync_at DATETIME,
    last_message_id TEXT,
    last_status TEXT DEFAULT 'never_run',
    messages_processed INTEGER DEFAULT 0,
    errors TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_contacts (
    id TEXT PRIMARY KEY,
    phone TEXT NOT NULL,
    display_name TEXT,
    source TEXT NOT NULL,
    first_seen_at DATETIME NOT NULL,
    last_seen_at DATETIME,
    message_count INTEGER DEFAULT 0,
    thread_ids TEXT,
    status TEXT DEFAULT 'pending',
    resolved_contact_id TEXT,
    reviewed_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now')),
    UNIQUE(phone, source)
);
"""
