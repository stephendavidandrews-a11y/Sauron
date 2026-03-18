"""Unified entity tables: organizations, legislation, topics."""

ENTITIES_SQL = """
CREATE TABLE IF NOT EXISTS unified_entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases TEXT,
    description TEXT,
    first_observed_at TEXT,
    last_observed_at TEXT,
    observation_count INTEGER DEFAULT 1,
    is_confirmed INTEGER DEFAULT 0,
    source_conversation_id TEXT,
    created_at DATETIME DEFAULT (datetime('now')),
    UNIQUE(entity_type, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_unified_entities_name ON unified_entities(canonical_name);

CREATE INDEX IF NOT EXISTS idx_unified_entities_type ON unified_entities(entity_type);

CREATE TABLE IF NOT EXISTS entity_organizations (
    entity_id TEXT PRIMARY KEY REFERENCES unified_entities(id) ON DELETE CASCADE,
    industry TEXT,
    org_category TEXT,
    headquarters TEXT,
    parent_org_entity_id TEXT,
    networking_app_org_id TEXT,
    website TEXT
);

CREATE TABLE IF NOT EXISTS entity_legislation (
    entity_id TEXT PRIMARY KEY REFERENCES unified_entities(id) ON DELETE CASCADE,
    bill_number TEXT,
    congress TEXT,
    chamber TEXT,
    committee TEXT,
    status TEXT,
    policy_area TEXT,
    sponsor_names TEXT
);

CREATE TABLE IF NOT EXISTS entity_topics (
    entity_id TEXT PRIMARY KEY REFERENCES unified_entities(id) ON DELETE CASCADE,
    domain TEXT,
    parent_topic_entity_id TEXT
);
"""
