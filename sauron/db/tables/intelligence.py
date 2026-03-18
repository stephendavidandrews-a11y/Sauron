"""Intelligence tables: claims, beliefs, knowledge graph, embeddings."""

INTELLIGENCE_SQL = """
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
    review_status TEXT,
    reviewed_at DATETIME,
    review_note TEXT,
    from_entity_id TEXT,
    from_entity_table TEXT,
    to_entity_id TEXT,
    to_entity_table TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_from_entity_id ON graph_edges(from_entity_id);

CREATE INDEX IF NOT EXISTS idx_graph_edges_source_conv ON graph_edges(source_conversation_id);

CREATE INDEX IF NOT EXISTS idx_graph_edges_from ON graph_edges(from_entity, from_type);

CREATE INDEX IF NOT EXISTS idx_graph_edges_to_entity_id ON graph_edges(to_entity_id);

CREATE INDEX IF NOT EXISTS idx_graph_edges_to ON graph_edges(to_entity, to_type);

CREATE INDEX IF NOT EXISTS idx_graph_edges_type ON graph_edges(edge_type);

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

CREATE INDEX IF NOT EXISTS idx_policy_positions_contact ON policy_positions(contact_id);

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

CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_embeddings_conversation ON embeddings(conversation_id);

CREATE INDEX IF NOT EXISTS idx_embeddings_contact ON embeddings(contact_id);

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

CREATE INDEX IF NOT EXISTS idx_event_episodes_type ON event_episodes(episode_type);

CREATE INDEX IF NOT EXISTS idx_event_episodes_conversation ON event_episodes(conversation_id);

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
    evidence_quality TEXT,
    due_date TEXT,
    date_confidence TEXT,
    date_note TEXT,
    condition_trigger TEXT,
    recurrence TEXT,
    related_claim_id TEXT,
    review_tier TEXT,
    subject_type TEXT DEFAULT 'person',
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_event_claims_due_date ON event_claims(due_date);

CREATE INDEX IF NOT EXISTS idx_event_claims_speaker ON event_claims(speaker_id);

CREATE INDEX IF NOT EXISTS idx_event_claims_type ON event_claims(claim_type);

CREATE INDEX IF NOT EXISTS idx_event_claims_review_tier ON event_claims(review_tier);

CREATE INDEX IF NOT EXISTS idx_event_claims_subject ON event_claims(subject_entity_id);

CREATE INDEX IF NOT EXISTS idx_event_claims_episode ON event_claims(episode_id);

CREATE INDEX IF NOT EXISTS idx_event_claims_review_status ON event_claims(review_status);

CREATE INDEX IF NOT EXISTS idx_event_claims_conversation ON event_claims(conversation_id);

CREATE TABLE IF NOT EXISTS claim_entities (
    id TEXT PRIMARY KEY,
    claim_id TEXT REFERENCES event_claims(id) ON DELETE CASCADE,
    entity_id TEXT REFERENCES unified_contacts(id),
    entity_name TEXT,
    entity_table TEXT DEFAULT 'unified_contacts',
    role TEXT DEFAULT 'subject',
    confidence REAL,
    link_source TEXT DEFAULT 'model',
    created_at DATETIME DEFAULT (datetime('now')),
    UNIQUE(claim_id, entity_id, role)
);

CREATE INDEX IF NOT EXISTS idx_claim_entities_source ON claim_entities(link_source);

CREATE INDEX IF NOT EXISTS idx_claim_entities_entity ON claim_entities(entity_id);

CREATE INDEX IF NOT EXISTS idx_claim_entities_claim ON claim_entities(claim_id);

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

CREATE INDEX IF NOT EXISTS idx_beliefs_status ON beliefs(status);

CREATE INDEX IF NOT EXISTS idx_beliefs_key ON beliefs(belief_key);

CREATE INDEX IF NOT EXISTS idx_beliefs_entity ON beliefs(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS belief_evidence (
    id TEXT PRIMARY KEY,
    belief_id TEXT REFERENCES beliefs(id),
    claim_id TEXT REFERENCES event_claims(id),
    weight REAL,
    evidence_role TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_belief_evidence_claim ON belief_evidence(claim_id);

CREATE INDEX IF NOT EXISTS idx_belief_evidence_belief ON belief_evidence(belief_id);

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

CREATE INDEX IF NOT EXISTS idx_what_changed_date ON what_changed_snapshots(snapshot_date);

CREATE INDEX IF NOT EXISTS idx_what_changed_entity ON what_changed_snapshots(entity_type, entity_id);

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

CREATE INDEX IF NOT EXISTS idx_resynth_status ON belief_resynthesis_proposals(status);

CREATE INDEX IF NOT EXISTS idx_resynth_belief ON belief_resynthesis_proposals(belief_id);
"""
