"""Routing tables: routing log, summaries, entity links, pending routes."""

ROUTING_SQL = """
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

CREATE INDEX IF NOT EXISTS idx_routing_log_status ON routing_log(status);

CREATE INDEX IF NOT EXISTS idx_routing_log_target ON routing_log(target_system);

CREATE INDEX IF NOT EXISTS idx_routing_log_entity ON routing_log(entity_id);

CREATE INDEX IF NOT EXISTS idx_routing_log_conversation ON routing_log(conversation_id);

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

CREATE INDEX IF NOT EXISTS idx_pending_routes_status ON pending_object_routes(released_at);

CREATE INDEX IF NOT EXISTS idx_pending_routes_entity ON pending_object_routes(blocked_on_entity);
"""
