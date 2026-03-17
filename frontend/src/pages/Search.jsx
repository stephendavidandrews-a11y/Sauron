import { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { fetchTextPendingContacts, approveTextContact, dismissTextContact, deferTextContact, triggerTextSync, fetchTextStatus } from '../api';

export const C = {
  bg: '#0a0f1a', card: '#111827', border: '#1f2937',
  text: '#e5e7eb', muted: '#9ca3af', dim: '#6b7280',
  accent: '#3b82f6', green: '#10b981', amber: '#f59e0b',
  red: '#ef4444', purple: '#a78bfa', gray: '#6b7280',
};


const STATUS_FAMILIES = {
  active: { label: 'Solid', color: '#10b981' },
  refined: { label: 'Solid', color: '#10b981' },
  provisional: { label: 'Shifting', color: '#f59e0b' },
  qualified: { label: 'Shifting', color: '#f59e0b' },
  time_bounded: { label: 'Shifting', color: '#f59e0b' },
  contested: { label: 'Contested', color: '#ef4444' },
  stale: { label: 'Stale', color: '#6b7280' },
  under_review: { label: 'Under Review', color: '#a78bfa' },
};

const BROWSE_FAMILIES = [
  { key: 'all', label: 'All' },
  { key: 'solid', label: 'Solid', statuses: ['active', 'refined'] },
  { key: 'shifting', label: 'Shifting', statuses: ['provisional', 'qualified', 'time_bounded'] },
  { key: 'contested', label: 'Contested', statuses: ['contested'] },
  { key: 'stale', label: 'Stale', statuses: ['stale'] },
  { key: 'under_review', label: 'Under Review', statuses: ['under_review'] },
];

// Module-level recent queries (persists across re-renders, resets on full page nav)
let recentQueriesStore = [];

function relativeTime(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  return date.toLocaleDateString();
}

function truncate(str, len) {
  if (!str) return '';
  return str.length > len ? str.slice(0, len) + '...' : str;
}

export default function Search() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialQuery = searchParams.get('q') || '';
  const [mode, setMode] = useState('search');
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [recentQueries, setRecentQueries] = useState(recentQueriesStore);
  const [showRecent, setShowRecent] = useState(false);
  const [sessionId] = useState(() => Math.random().toString(36).slice(2, 10));
  const searchTimestampRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  useEffect(() => {
    const q = searchParams.get('q');
    if (q && q !== query) {
      setQuery(q);
      doSearch(q);
    }
  }, [searchParams]);

  const doSearch = async (q) => {
    if (!q.trim()) return;
    setLoading(true);
    searchTimestampRef.current = Date.now();
    try {
      const data = await api.unifiedSearch(q.trim());
      setResults(data);
      // Telemetry
      const sections = {};
      if (data.people?.length) sections.people = data.people.length;
      if (data.beliefs?.length) sections.beliefs = data.beliefs.length;
      if (data.evidence?.length) sections.evidence = data.evidence.length;
      if (data.transcripts?.length) sections.transcripts = data.transcripts.length;
      const total = Object.values(sections).reduce((a, b) => a + b, 0);
      api.logSearchEvent({
        query: q.trim(),
        query_type: 'search',
        sections_returned: JSON.stringify(sections),
        result_count: total,
        session_id: sessionId,
      });
    } catch {
      setResults({ people: [], beliefs: [], evidence: [], transcripts: [] });
    }
    setLoading(false);
    // Update recent queries
    recentQueriesStore = [q.trim(), ...recentQueriesStore.filter(x => x !== q.trim())].slice(0, 15);
    setRecentQueries([...recentQueriesStore]);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setShowRecent(false);
    // Check commands first
    for (const cmd of COMMANDS) {
      const m = q.match(cmd.pattern);
      if (m) {
        const path = typeof cmd.path === 'function' ? cmd.path(m) : cmd.path;
        navigate(path);
        return;
      }
    }
    navigate(`/search?q=${encodeURIComponent(q)}`, { replace: true });
    doSearch(q);
  };

  const logClick = (section, sourceType, id) => {
    const elapsed = searchTimestampRef.current ? Date.now() - searchTimestampRef.current : null;
    api.logSearchEvent({
      query: query.trim(),
      query_type: 'search',
      result_clicked: JSON.stringify({ section, source_type: sourceType, id }),
      time_to_click_ms: elapsed,
      session_id: sessionId,
    });
  };

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '32px 16px' }}>
      {/* Mode toggle */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: C.text, margin: 0 }}>Search</h1>
        <div style={{ display: 'flex', gap: 4, background: C.card, borderRadius: 8, padding: 3, border: `1px solid ${C.border}` }}>
          {['search', 'browse'].map(m => (
            <button key={m} onClick={() => setMode(m)}
              style={{
                padding: '6px 14px', borderRadius: 6, fontSize: 13, fontWeight: 500,
                border: 'none', cursor: 'pointer',
                background: mode === m ? C.accent : 'transparent',
                color: mode === m ? '#fff' : C.muted,
              }}>
              {m === 'search' ? 'Search' : 'Browse Beliefs'}
            </button>
          ))}
        </div>
      </div>

      {mode === 'search' && (
        <>
          {/* Search input */}
          <form onSubmit={handleSubmit} style={{ position: 'relative' }}>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => setShowRecent(true)}
              onBlur={() => setTimeout(() => setShowRecent(false), 200)}
              placeholder="Search conversations, claims, people, beliefs..."
              style={{
                width: '100%', padding: '12px 16px', borderRadius: 10, fontSize: 15,
                border: `1px solid ${C.border}`, background: C.card, color: C.text,
                outline: 'none', boxSizing: 'border-box',
              }}
            />
            {/* Recent queries dropdown */}
            {showRecent && !query && recentQueries.length > 0 && (
              <div style={{
                position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4,
                background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
                zIndex: 10, maxHeight: 300, overflowY: 'auto',
              }}>
                <div style={{ padding: '8px 12px', fontSize: 11, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Recent Searches
                </div>
                {recentQueries.map((q, i) => (
                  <div key={i}
                    onMouseDown={() => { setQuery(q); setShowRecent(false); doSearch(q); }}
                    style={{
                      padding: '8px 14px', cursor: 'pointer', fontSize: 13, color: C.text,
                      borderTop: `1px solid ${C.border}`,
                    }}>
                    {q}
                  </div>
                ))}
              </div>
            )}
          </form>
          <div style={{ fontSize: 11, color: C.dim, marginTop: 6, marginBottom: 20 }}>
            prep [name] &middot; call [name] &middot; topic [keyword] &middot; or just search
          </div>

          {loading && (
            <div style={{ textAlign: 'center', color: C.muted, padding: '40px 0' }}>Searching...</div>
          )}

          {results && !loading && (
            <div>
              <PeopleSection people={results.people} navigate={navigate} logClick={logClick} />
              <BeliefsSection beliefs={results.beliefs} navigate={navigate} logClick={logClick} />
              <EvidenceSection evidence={results.evidence} navigate={navigate} logClick={logClick} />
              <TranscriptsSection
                transcripts={results.transcripts}
                evidenceCount={results.evidence?.length || 0}
                navigate={navigate} logClick={logClick}
              />
              {!results.people?.length && !results.beliefs?.length &&
               !results.evidence?.length && !results.transcripts?.length && (
                <div style={{ textAlign: 'center', padding: '40px 0', color: C.muted }}>
                  <p style={{ fontSize: 15, marginBottom: 4 }}>No results for "{query}"</p>
                  <p style={{ fontSize: 13 }}>Try different keywords or a broader search.</p>
                </div>
              )}
            </div>
          )}

          {!results && !loading && (
            <div style={{ textAlign: 'center', padding: '48px 0', color: C.muted }}>
              <p style={{ fontSize: 16, marginBottom: 6 }}>Semantic search across all conversations.</p>
              <p style={{ fontSize: 13 }}>Try "Heath stablecoins" or "who mentioned jurisdiction"</p>
            </div>
          )}
        </>
      )}

      {mode === 'browse' && <BeliefsBrowse navigate={navigate} />}

      {/* Admin: Contact Sync (preserved) */}
      <ContactSyncPanel />
      <PendingTextContactsPanel />
    </div>
  );
}


// ═══════════════════════════════════════════════════════
// PEOPLE SECTION
// ═══════════════════════════════════════════════════════
function PeopleSection({ people, navigate, logClick }) {
  const [showAll, setShowAll] = useState(false);
  if (!people?.length) return null;
  const visible = showAll ? people : people.slice(0, 5);

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>People</span>
        <span style={{ fontSize: 12, color: C.dim }}>{people.length}</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {visible.map(p => (
          <div key={p.id}
            onClick={() => { logClick('people', 'contact', p.id); navigate(`/prep/${encodeURIComponent(p.canonical_name)}`); }}
            style={{
              padding: '10px 14px', borderRadius: 8, cursor: 'pointer',
              background: C.card, border: `1px solid ${C.border}`,
              minWidth: 180, flex: '1 1 220px', maxWidth: 300,
            }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 4 }}>
              {p.canonical_name}
            </div>
            <div style={{ display: 'flex', gap: 10, fontSize: 11, color: C.dim }}>
              {p.conversation_count > 0 && <span>{p.conversation_count} convos</span>}
              {p.last_interaction && <span>{relativeTime(p.last_interaction)}</span>}
              {p.voice_enrolled ? <span style={{ color: C.green }}>Voice enrolled</span> : null}
            </div>
          </div>
        ))}
      </div>
      {people.length > 5 && !showAll && (
        <button onClick={() => setShowAll(true)}
          style={{ marginTop: 6, fontSize: 12, color: C.accent, background: 'none', border: 'none', cursor: 'pointer' }}>
          Show {people.length - 5} more
        </button>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════
// BELIEFS SECTION
// ═══════════════════════════════════════════════════════
function BeliefsSection({ beliefs, navigate, logClick }) {
  if (!beliefs?.length) return null;
  const visible = beliefs.slice(0, 5);

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>Beliefs</span>
        <span style={{ fontSize: 12, color: C.dim }}>{beliefs.length}</span>
      </div>
      {visible.map(b => {
        const fam = STATUS_FAMILIES[b.status] || { label: b.status, color: C.dim };
        return (
          <div key={b.id}
            onClick={() => { logClick('beliefs', 'belief', b.id); navigate('/review/beliefs'); }}
            style={{
              padding: '12px 14px', borderRadius: 8, marginBottom: 6, cursor: 'pointer',
              background: C.card, border: `1px solid ${C.border}`,
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{
                fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                background: fam.color + '22', color: fam.color,
              }}>
                {fam.label}
              </span>
              {b.entity_name && (
                <span style={{ fontSize: 11, color: C.muted }}>{b.entity_name}</span>
              )}
            </div>
            <div style={{ fontSize: 13, color: C.text, lineHeight: 1.4 }}>
              {b.belief_summary}
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 6, fontSize: 11, color: C.dim }}>
              {b.support_count > 0 && <span>{b.support_count} supporting claims</span>}
              {b.confidence >= 0.7 && <span>{Math.round(b.confidence * 100)}%</span>}
              {b.last_confirmed_at && <span>{relativeTime(b.last_confirmed_at)}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}


// ═══════════════════════════════════════════════════════
// EVIDENCE SECTION (grouped by conversation)
// ═══════════════════════════════════════════════════════
function EvidenceSection({ evidence, navigate, logClick }) {
  const [showAllGroups, setShowAllGroups] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState({});
  if (!evidence?.length) return null;

  const totalHits = evidence.reduce((sum, g) => sum + (g.hits?.length || 0), 0);
  const visibleGroups = showAllGroups ? evidence : evidence.slice(0, 7);

  const toggleGroup = (cid) => {
    setExpandedGroups(prev => ({ ...prev, [cid]: !prev[cid] }));
  };

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>Evidence</span>
        <span style={{ fontSize: 12, color: C.dim }}>{totalHits} hits in {evidence.length} conversations</span>
      </div>
      {visibleGroups.map(group => {
        const expanded = expandedGroups[group.conversation_id];
        const visibleHits = expanded ? group.hits : (group.hits || []).slice(0, 3);
        const hiddenCount = (group.hits?.length || 0) - 3;

        return (
          <div key={group.conversation_id}
            style={{
              marginBottom: 10, borderRadius: 8, overflow: 'hidden',
              border: `1px solid ${C.border}`, background: C.card,
            }}>
            {/* Conversation group header */}
            <div style={{
              padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 8,
              borderBottom: `1px solid ${C.border}`, background: C.bg,
            }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.text, flex: 1 }}>
                {group.label || 'Conversation'}
              </span>
              {group.captured_at && (
                <span style={{ fontSize: 11, color: C.dim }}>{relativeTime(group.captured_at)}</span>
              )}
              {group.context_classification && (
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 3,
                  background: C.accent + '18', color: C.accent,
                }}>
                  {group.context_classification}
                </span>
              )}
              {group.source && (
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 3,
                  background: C.border, color: C.muted,
                }}>
                  {group.source}
                </span>
              )}
            </div>

            {/* Evidence hits within this conversation */}
            {visibleHits.map((hit, idx) => (
              <EvidenceHit key={hit.source_id || idx} hit={hit} navigate={navigate}
                logClick={logClick} conversationId={group.conversation_id} />
            ))}

            {/* Show more within group */}
            {hiddenCount > 0 && !expanded && (
              <button onClick={() => toggleGroup(group.conversation_id)}
                style={{
                  width: '100%', padding: '8px', fontSize: 12, color: C.accent,
                  background: 'transparent', border: 'none', borderTop: `1px solid ${C.border}`,
                  cursor: 'pointer',
                }}>
                Show {hiddenCount} more from this conversation
              </button>
            )}
          </div>
        );
      })}
      {evidence.length > 7 && !showAllGroups && (
        <button onClick={() => setShowAllGroups(true)}
          style={{ marginTop: 4, fontSize: 12, color: C.accent, background: 'none', border: 'none', cursor: 'pointer' }}>
          Show {evidence.length - 7} more conversations
        </button>
      )}
    </div>
  );
}

export const CLAIM_TYPE_COLORS = {
  fact: '#3b82f6', position: '#8b5cf6', commitment: '#f59e0b',
  preference: '#ec4899', relationship: '#10b981', observation: '#6366f1',
  tactical: '#f97316',
};

export function EvidenceHit({ hit, navigate, logClick, conversationId }) {
  const handleClick = () => {
    logClick('evidence', hit.source_type, hit.source_id);
    navigate(`/review/${conversationId}`);
  };

  if (hit.source_type === 'claim') {
    const typeColor = CLAIM_TYPE_COLORS[hit.claim_type] || C.dim;
    return (
      <div onClick={handleClick}
        style={{ padding: '10px 14px', cursor: 'pointer', borderTop: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, flexWrap: 'wrap' }}>
          <span style={{
            fontSize: 10, padding: '1px 5px', borderRadius: 3, fontWeight: 600,
            background: typeColor + '22', color: typeColor,
          }}>
            {hit.claim_type}
          </span>
          {hit.modality && hit.modality !== 'stated' && (
            <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: C.border, color: C.muted }}>
              {hit.modality}
            </span>
          )}
          {hit.speaker_name && (
            <span style={{ fontSize: 11, color: C.muted }}>{hit.speaker_name}</span>
          )}
          {hit.subject_name && hit.subject_name !== hit.speaker_name && (
            <span style={{ fontSize: 11, color: C.dim }}>about {hit.subject_name}</span>
          )}
          {hit.confidence >= 0.7 && (
            <span style={{
              width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
              background: hit.confidence >= 0.9 ? C.green : hit.confidence >= 0.8 ? C.amber : C.dim,
            }} />
          )}
          <span style={{ fontSize: 10, color: C.dim, marginLeft: 'auto' }}>
            {Math.round((hit.similarity || 0) * 100)}%
          </span>
        </div>
        <div style={{ fontSize: 13, color: C.text, lineHeight: 1.4 }}>
          {truncate(hit.claim_text || hit.text, 150)}
        </div>
        {hit.evidence_quote && (
          <div style={{
            fontSize: 12, color: C.dim, fontStyle: 'italic', marginTop: 4,
            borderLeft: `2px solid ${C.border}`, paddingLeft: 8,
          }}>
            "{truncate(hit.evidence_quote, 120)}"
          </div>
        )}
      </div>
    );
  }

  if (hit.source_type === 'episode') {
    return (
      <div onClick={handleClick}
        style={{ padding: '10px 14px', cursor: 'pointer', borderTop: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <span style={{
            fontSize: 10, padding: '1px 5px', borderRadius: 3, fontWeight: 600,
            background: C.purple + '22', color: C.purple,
          }}>
            {hit.episode_type || 'episode'}
          </span>
          <span style={{ fontSize: 13, fontWeight: 500, color: C.text }}>{hit.title}</span>
          <span style={{ fontSize: 10, color: C.dim, marginLeft: 'auto' }}>
            {Math.round((hit.similarity || 0) * 100)}%
          </span>
        </div>
        <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.4 }}>
          {truncate(hit.summary || hit.text, 200)}
        </div>
      </div>
    );
  }

  // Other types: extraction_summary, commitment, follow_up, belief
  return (
    <div onClick={handleClick}
      style={{ padding: '10px 14px', cursor: 'pointer', borderTop: `1px solid ${C.border}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{
          fontSize: 10, padding: '1px 5px', borderRadius: 3,
          background: C.border, color: C.muted,
        }}>
          {hit.source_type.replace('_', ' ')}
        </span>
        <span style={{ fontSize: 10, color: C.dim, marginLeft: 'auto' }}>
          {Math.round((hit.similarity || 0) * 100)}%
        </span>
      </div>
      <div style={{ fontSize: 13, color: C.text, lineHeight: 1.4 }}>
        {truncate(hit.text, 200)}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════
// TRANSCRIPTS SECTION (fallback)
// ═══════════════════════════════════════════════════════
function TranscriptsSection({ transcripts, evidenceCount, navigate, logClick }) {
  if (!transcripts?.length) return null;
  if (evidenceCount >= 5) return null;

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>Transcript matches</span>
        <span style={{ fontSize: 12, color: C.dim }}>{transcripts.length}</span>
      </div>
      {transcripts.slice(0, 5).map((t, i) => (
        <div key={i}
          onClick={() => {
            logClick('transcripts', 'transcript_segment', t.conversation_id);
            if (t.conversation_id) navigate(`/review/${t.conversation_id}`);
          }}
          style={{
            padding: '10px 14px', marginBottom: 4, borderRadius: 6, cursor: 'pointer',
            background: C.card, border: `1px solid ${C.border}`,
          }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            {t.speaker_label && (
              <span style={{ fontSize: 11, fontWeight: 600, color: C.accent }}>{t.speaker_label}</span>
            )}
            {t.captured_at && (
              <span style={{ fontSize: 11, color: C.dim, marginLeft: 'auto' }}>{relativeTime(t.captured_at)}</span>
            )}
          </div>
          <div style={{ fontSize: 13, color: C.text, lineHeight: 1.4 }}>
            {truncate(t.text, 200)}
          </div>
        </div>
      ))}
    </div>
  );
}


// ═══════════════════════════════════════════════════════
// BELIEFS BROWSE MODE
// ═══════════════════════════════════════════════════════
function BeliefsBrowse({ navigate }) {
  const [personQuery, setPersonQuery] = useState('');
  const [personResults, setPersonResults] = useState([]);
  const [selectedContact, setSelectedContact] = useState(null);
  const [topicKeyword, setTopicKeyword] = useState('');
  const [statusFamily, setStatusFamily] = useState('all');
  const [beliefs, setBeliefs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showPersonDropdown, setShowPersonDropdown] = useState(false);
  const debounceRef = useRef(null);

  // Search contacts as user types
  const searchPeople = useCallback((q) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) { setPersonResults([]); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await api.searchContacts(q.trim());
        setPersonResults(data.contacts || data || []);
        setShowPersonDropdown(true);
      } catch { setPersonResults([]); }
    }, 250);
  }, []);

  // Load beliefs when filters change
  useEffect(() => {
    loadBeliefs();
  }, [selectedContact, statusFamily]);

  const loadBeliefs = async () => {
    setLoading(true);
    try {
      let data;
      if (selectedContact) {
        data = await api.beliefsByContact(selectedContact.id, 50);
      } else if (topicKeyword.trim()) {
        data = await api.beliefsByTopic(topicKeyword.trim(), 50);
      } else {
        const statusFilter = statusFamily === 'all' ? null :
          BROWSE_FAMILIES.find(f => f.key === statusFamily)?.statuses?.[0] || null;
        data = await api.beliefs({ limit: 50, status: statusFilter });
      }
      let results = Array.isArray(data) ? data : (data.beliefs || data || []);
      // Filter by status family client-side
      if (statusFamily !== 'all') {
        const allowedStatuses = BROWSE_FAMILIES.find(f => f.key === statusFamily)?.statuses || [];
        results = results.filter(b => allowedStatuses.includes(b.status));
      }
      // Sort by confidence DESC, then last_changed_at DESC
      results.sort((a, b) => {
        const confDiff = (b.confidence || 0) - (a.confidence || 0);
        if (confDiff !== 0) return confDiff;
        return (b.last_changed_at || '').localeCompare(a.last_changed_at || '');
      });
      setBeliefs(results);
    } catch {
      setBeliefs([]);
    }
    setLoading(false);
  };

  const handleTopicSearch = (e) => {
    e.preventDefault();
    loadBeliefs();
  };

  return (
    <div>
      {/* Filter controls */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        {/* Person filter */}
        <div style={{ flex: '1 1 200px', position: 'relative' }}>
          <label style={{ fontSize: 11, color: C.dim, display: 'block', marginBottom: 3 }}>Person</label>
          <input
            type="text"
            value={selectedContact ? selectedContact.canonical_name : personQuery}
            onChange={(e) => {
              setPersonQuery(e.target.value);
              setSelectedContact(null);
              searchPeople(e.target.value);
            }}
            onFocus={() => { if (personResults.length) setShowPersonDropdown(true); }}
            onBlur={() => setTimeout(() => setShowPersonDropdown(false), 200)}
            placeholder="Search contacts..."
            style={{
              width: '100%', padding: '8px 10px', borderRadius: 6, fontSize: 13,
              border: `1px solid ${C.border}`, background: C.card, color: C.text,
              outline: 'none', boxSizing: 'border-box',
            }}
          />
          {showPersonDropdown && personResults.length > 0 && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 2,
              background: C.card, border: `1px solid ${C.border}`, borderRadius: 6,
              zIndex: 10, maxHeight: 200, overflowY: 'auto',
            }}>
              {personResults.slice(0, 10).map(c => (
                <div key={c.id}
                  onMouseDown={() => {
                    setSelectedContact(c);
                    setPersonQuery('');
                    setShowPersonDropdown(false);
                  }}
                  style={{
                    padding: '8px 10px', cursor: 'pointer', fontSize: 13, color: C.text,
                    borderBottom: `1px solid ${C.border}`,
                  }}>
                  {c.canonical_name}
                </div>
              ))}
            </div>
          )}
          {selectedContact && (
            <button onClick={() => { setSelectedContact(null); setPersonQuery(''); }}
              style={{
                position: 'absolute', right: 8, top: 22, fontSize: 12,
                color: C.dim, background: 'none', border: 'none', cursor: 'pointer',
              }}>
              \u2715
            </button>
          )}
        </div>

        {/* Topic filter */}
        <div style={{ flex: '1 1 200px' }}>
          <label style={{ fontSize: 11, color: C.dim, display: 'block', marginBottom: 3 }}>Topic</label>
          <form onSubmit={handleTopicSearch} style={{ display: 'flex', gap: 4 }}>
            <input
              type="text"
              value={topicKeyword}
              onChange={(e) => setTopicKeyword(e.target.value)}
              placeholder="Keyword..."
              style={{
                flex: 1, padding: '8px 10px', borderRadius: 6, fontSize: 13,
                border: `1px solid ${C.border}`, background: C.card, color: C.text,
                outline: 'none', boxSizing: 'border-box',
              }}
            />
            <button type="submit" style={{
              padding: '8px 12px', borderRadius: 6, fontSize: 12,
              border: `1px solid ${C.accent}44`, background: C.accent + '18',
              color: C.accent, cursor: 'pointer',
            }}>Go</button>
          </form>
        </div>

        {/* Status family filter */}
        <div style={{ flex: '1 1 180px' }}>
          <label style={{ fontSize: 11, color: C.dim, display: 'block', marginBottom: 3 }}>Status</label>
          <select
            value={statusFamily}
            onChange={(e) => setStatusFamily(e.target.value)}
            style={{
              width: '100%', padding: '8px 10px', borderRadius: 6, fontSize: 13,
              border: `1px solid ${C.border}`, background: C.card, color: C.text,
              outline: 'none',
            }}>
            {BROWSE_FAMILIES.map(f => (
              <option key={f.key} value={f.key}>{f.label}</option>
            ))}
          </select>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', color: C.muted, padding: '40px 0' }}>Loading beliefs...</div>
      )}

      {!loading && beliefs.length === 0 && (
        <div style={{ textAlign: 'center', color: C.muted, padding: '40px 0', fontSize: 13 }}>
          No beliefs found. Try adjusting filters.
        </div>
      )}

      {!loading && beliefs.map(b => {
        const fam = STATUS_FAMILIES[b.status] || { label: b.status, color: C.dim };
        return (
          <div key={b.id}
            onClick={() => navigate('/review/beliefs')}
            style={{
              padding: '14px', borderRadius: 8, marginBottom: 8, cursor: 'pointer',
              background: C.card, border: `1px solid ${C.border}`,
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{
                fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                background: fam.color + '22', color: fam.color,
              }}>
                {fam.label}
              </span>
              {b.entity_name && (
                <span style={{ fontSize: 12, color: C.muted }}>{b.entity_name}</span>
              )}
              {b.confidence >= 0.7 && (
                <span style={{ fontSize: 11, color: C.dim, marginLeft: 'auto' }}>
                  {Math.round(b.confidence * 100)}%
                </span>
              )}
            </div>
            <div style={{ fontSize: 14, color: C.text, lineHeight: 1.4, marginBottom: 4 }}>
              {b.belief_summary}
            </div>
            {b.belief_key && (
              <div style={{ fontSize: 11, color: C.dim, marginBottom: 6 }}>{b.belief_key}</div>
            )}
            <div style={{ display: 'flex', gap: 12, fontSize: 11, color: C.dim, flexWrap: 'wrap' }}>
              {b.support_count > 0 && <span>{b.support_count} supporting</span>}
              {b.contradiction_count > 0 && (
                <span style={{ color: C.red }}>{b.contradiction_count} contradictions</span>
              )}
              {b.first_observed_at && <span>First seen: {relativeTime(b.first_observed_at)}</span>}
              {b.last_changed_at && <span>Changed: {relativeTime(b.last_changed_at)}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}


// ═══════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════
// PENDING TEXT CONTACTS PANEL — approve/dismiss unknown senders
// ═══════════════════════════════════════════════════════
function PendingTextContactsPanel() {
  const [open, setOpen] = useState(false);
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [approveForm, setApproveForm] = useState(null); // { id, phone, display_name }
  const [formData, setFormData] = useState({ name: '', organization: '', title: '', email: '' });
  const [actionResult, setActionResult] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [showDeferred, setShowDeferred] = useState(false);

  const loadContacts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchTextPendingContacts();
      setContacts(data || []);
    } catch (e) {
      console.error('Failed to load pending contacts:', e);
    }
    setLoading(false);
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const s = await fetchTextStatus();
      setPipelineStatus(s);
    } catch (e) {
      console.error('Failed to load text status:', e);
    }
  }, []);

  useEffect(() => {
    if (open && contacts.length === 0) {
      loadContacts();
      loadStatus();
    }
  }, [open, loadContacts, loadStatus, contacts.length]);

  const handleApprove = async () => {
    if (!formData.name.trim()) return;
    try {
      const result = await approveTextContact(approveForm.id, {
        name: formData.name.trim(),
        organization: formData.organization.trim() || null,
        title: formData.title.trim() || null,
        email: formData.email.trim() || null,
      });
      setActionResult({ type: 'success', text: `Approved: ${result.name} (${result.phone})` });
      setApproveForm(null);
      setFormData({ name: '', organization: '', title: '', email: '' });
      loadContacts();
    } catch (e) {
      setActionResult({ type: 'error', text: `Approve failed: ${e.message}` });
    }
  };

  const handleDismiss = async (id) => {
    try {
      await dismissTextContact(id);
      setActionResult({ type: 'success', text: 'Contact dismissed' });
      loadContacts();
    } catch (e) {
      setActionResult({ type: 'error', text: `Dismiss failed: ${e.message}` });
    }
  };

  const handleDefer = async (id) => {
    try {
      await deferTextContact(id);
      setActionResult({ type: 'success', text: 'Contact deferred' });
      loadContacts();
    } catch (e) {
      setActionResult({ type: 'error', text: `Defer failed: ${e.message}` });
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const result = await triggerTextSync(false);
      setSyncResult({ type: 'success', text: 'Sync started. New threads will be processed within ~30s.' });
      // Refresh status after a short delay
      setTimeout(() => loadStatus(), 5000);
    } catch (e) {
      setSyncResult({ type: 'error', text: `Sync failed: ${e.message}` });
    }
    setSyncing(false);
  };

  const pendingContacts = contacts.filter(c => c.status === 'pending');
  const deferredContacts = contacts.filter(c => c.status === 'deferred');
  const phoneContacts = pendingContacts.filter(c => c.phone && c.phone.length > 0);
  const extractionContacts = pendingContacts.filter(c => !c.phone || c.phone.length === 0);

  return (
    <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 16, marginTop: 16 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, background: 'none',
          border: 'none', cursor: 'pointer', padding: 0, color: C.dim,
        }}>
        <span style={{ fontSize: 10 }}>{open ? '\u25BC' : '\u25B6'}</span>
        <span style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
          Text Pipeline
        </span>
        {pendingContacts.length > 0 && (
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 8,
            background: '#f59e0b33', color: '#f59e0b', fontWeight: 600,
          }}>{pendingContacts.length}</span>
        )}
      </button>

      {open && (
        <div style={{ marginTop: 16 }}>
          {/* Pipeline Health Bar */}
          {pipelineStatus && (
            <div style={{
              background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
              padding: '12px 16px', marginBottom: 12,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              fontSize: 12,
            }}>
              <div style={{ display: 'flex', gap: 16, color: C.muted }}>
                <span>
                  <span style={{ color: pipelineStatus.sync?.status === 'ok' ? '#10b981' : pipelineStatus.sync?.status === 'warning' ? '#f59e0b' : '#ef4444', marginRight: 4 }}>\u25CF</span>
                  {pipelineStatus.sync?.detail || 'Unknown'}
                </span>
                <span>{pipelineStatus.ingest?.total_messages || 0} messages</span>
                <span>{pipelineStatus.threads?.total_threads || 0} threads</span>
                <span>{pipelineStatus.threads?.whitelisted || 0} whitelisted</span>
              </div>
              <button onClick={handleSync} disabled={syncing}
                style={{
                  fontSize: 11, padding: '4px 10px', borderRadius: 4,
                  border: `1px solid ${C.accent}44`, cursor: syncing ? 'default' : 'pointer',
                  background: syncing ? 'transparent' : C.accent + '18',
                  color: C.accent, opacity: syncing ? 0.6 : 1,
                }}>
                {syncing ? 'Syncing...' : 'Sync Now'}
              </button>
            </div>
          )}

          {syncResult && (
            <div style={{
              padding: '8px 12px', borderRadius: 6, fontSize: 12, marginBottom: 12,
              background: syncResult.type === 'success' ? '#10b98112' : '#ef444412',
              border: `1px solid ${syncResult.type === 'success' ? '#10b98133' : '#ef444433'}`,
              color: syncResult.type === 'success' ? '#10b981' : '#ef4444',
            }}>{syncResult.text}</div>
          )}

          {actionResult && (
            <div style={{
              padding: '8px 12px', borderRadius: 6, fontSize: 12, marginBottom: 12,
              background: actionResult.type === 'success' ? '#10b98112' : '#ef444412',
              border: `1px solid ${actionResult.type === 'success' ? '#10b98133' : '#ef444433'}`,
              color: actionResult.type === 'success' ? '#10b981' : '#ef4444',
            }}>{actionResult.text}</div>
          )}

          {/* Pending Contacts List */}
          <div style={{
            background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: 16,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: C.muted, margin: 0 }}>
                Pending Text Contacts
                {phoneContacts.length > 0 && (
                  <span style={{ fontSize: 12, fontWeight: 400, color: C.dim, marginLeft: 8 }}>
                    {phoneContacts.length} phone-based
                    {extractionContacts.length > 0 && `, ${extractionContacts.length} extraction-based`}
                  </span>
                )}
              </h3>
              <button onClick={loadContacts} disabled={loading}
                style={{ fontSize: 11, padding: '3px 8px', borderRadius: 4, border: `1px solid ${C.border}`,
                  background: 'transparent', color: C.dim, cursor: 'pointer' }}>
                {loading ? '...' : 'Refresh'}
              </button>
            </div>

            <p style={{ fontSize: 12, color: C.dim, marginBottom: 12, marginTop: 0 }}>
              Unknown phone numbers from iMessage threads. Approve to whitelist their threads for intelligence extraction.
            </p>

            {loading && <div style={{ padding: 12, textAlign: 'center', color: C.dim, fontSize: 13 }}>Loading...</div>}

            {!loading && phoneContacts.length === 0 && (
              <div style={{ padding: 12, textAlign: 'center', color: C.dim, fontSize: 13 }}>
                No pending contacts to review.
              </div>
            )}

            {!loading && phoneContacts.map(contact => (
              <div key={contact.id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 12px', borderRadius: 6, marginBottom: 4,
                background: approveForm?.id === contact.id ? '#1e293b' : 'transparent',
                border: approveForm?.id === contact.id ? `1px solid ${C.accent}44` : '1px solid transparent',
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: C.accent, fontSize: 13, fontFamily: 'monospace' }}>{contact.phone}</span>
                    {contact.display_name && (
                      <span style={{ color: C.muted, fontSize: 12 }}>({contact.display_name})</span>
                    )}
                    <span style={{ color: C.dim, fontSize: 11 }}>
                      {contact.message_count} msg{contact.message_count !== 1 ? 's' : ''}
                    </span>
                    {contact.thread_ids && (
                      <span style={{ color: C.dim, fontSize: 11 }}>
                        in {JSON.parse(contact.thread_ids).length} thread{JSON.parse(contact.thread_ids).length !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>

                  {/* Approve form (inline) */}
                  {approveForm?.id === contact.id && (
                    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <input
                          type="text" placeholder="Full name *" value={formData.name}
                          onChange={e => setFormData(d => ({ ...d, name: e.target.value }))}
                          autoFocus
                          onKeyDown={e => { if (e.key === 'Enter' && formData.name.trim()) handleApprove(); if (e.key === 'Escape') setApproveForm(null); }}
                          style={{
                            flex: 1, padding: '6px 10px', borderRadius: 4, fontSize: 13,
                            background: '#0f172a', border: `1px solid ${C.border}`, color: C.text,
                            outline: 'none',
                          }}
                        />
                        <input
                          type="text" placeholder="Organization" value={formData.organization}
                          onChange={e => setFormData(d => ({ ...d, organization: e.target.value }))}
                          style={{
                            flex: 1, padding: '6px 10px', borderRadius: 4, fontSize: 13,
                            background: '#0f172a', border: `1px solid ${C.border}`, color: C.text,
                            outline: 'none',
                          }}
                        />
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button onClick={handleApprove} disabled={!formData.name.trim()}
                          style={{
                            fontSize: 12, padding: '5px 12px', borderRadius: 4,
                            border: 'none', cursor: formData.name.trim() ? 'pointer' : 'default',
                            background: formData.name.trim() ? '#10b981' : '#10b98144',
                            color: 'white', fontWeight: 600,
                          }}>
                          Approve
                        </button>
                        <button onClick={() => { setApproveForm(null); setFormData({ name: '', organization: '', title: '', email: '' }); }}
                          style={{
                            fontSize: 12, padding: '5px 12px', borderRadius: 4,
                            border: `1px solid ${C.border}`, background: 'transparent',
                            color: C.dim, cursor: 'pointer',
                          }}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* Action buttons */}
                {approveForm?.id !== contact.id && (
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button onClick={() => {
                      setApproveForm(contact);
                      setFormData({ name: contact.display_name || '', organization: '', title: '', email: '' });
                      setActionResult(null);
                    }}
                      style={{
                        fontSize: 11, padding: '4px 10px', borderRadius: 4,
                        border: `1px solid #10b98144`, background: '#10b98112',
                        color: '#10b981', cursor: 'pointer',
                      }}>
                      Approve
                    </button>
                    <button onClick={() => handleDefer(contact.id)}
                      style={{
                        fontSize: 11, padding: '4px 10px', borderRadius: 4,
                        border: `1px solid ${C.border}`, background: 'transparent',
                        color: C.dim, cursor: 'pointer',
                      }}>
                      Defer
                    </button>
                    <button onClick={() => { if (window.confirm(`Dismiss ${contact.phone}? This contact will be permanently ignored.`)) handleDismiss(contact.id); }}
                      style={{
                        fontSize: 11, padding: '4px 10px', borderRadius: 4,
                        border: `1px solid #ef444433`, background: 'transparent',
                        color: '#ef4444', cursor: 'pointer', opacity: 0.7,
                      }}>
                      Dismiss
                    </button>
                  </div>
                )}
              </div>
            ))}

            {/* Deferred section */}
            {deferredContacts.length > 0 && (
              <div style={{ marginTop: 12, borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
                <button onClick={() => setShowDeferred(!showDeferred)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6, background: 'none',
                    border: 'none', cursor: 'pointer', padding: 0, color: C.dim, fontSize: 12,
                  }}>
                  <span style={{ fontSize: 9 }}>{showDeferred ? '\u25BC' : '\u25B6'}</span>
                  {deferredContacts.length} deferred contact{deferredContacts.length !== 1 ? 's' : ''}
                </button>
                {showDeferred && deferredContacts.map(contact => (
                  <div key={contact.id} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '8px 12px', marginTop: 4, borderRadius: 6, opacity: 0.6,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ color: C.dim, fontSize: 13, fontFamily: 'monospace' }}>{contact.phone}</span>
                      {contact.display_name && (
                        <span style={{ color: C.dim, fontSize: 12 }}>({contact.display_name})</span>
                      )}
                      <span style={{ color: C.dim, fontSize: 11 }}>{contact.message_count} msgs</span>
                    </div>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button onClick={() => {
                        setApproveForm(contact);
                        setFormData({ name: contact.display_name || '', organization: '', title: '', email: '' });
                      }}
                        style={{
                          fontSize: 11, padding: '3px 8px', borderRadius: 4,
                          border: `1px solid #10b98144`, background: '#10b98112',
                          color: '#10b981', cursor: 'pointer',
                        }}>
                        Approve
                      </button>
                      <button onClick={() => { if (window.confirm(`Dismiss ${contact.phone}?`)) handleDismiss(contact.id); }}
                        style={{
                          fontSize: 11, padding: '3px 8px', borderRadius: 4,
                          border: `1px solid #ef444433`, background: 'transparent',
                          color: '#ef4444', cursor: 'pointer', opacity: 0.7,
                        }}>
                        Dismiss
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}


// CONTACT SYNC PANEL — collapsible admin area (preserved)
// ═══════════════════════════════════════════════════════
function ContactSyncPanel() {
  const [open, setOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const result = await api.syncContacts();
      setSyncResult(result);
    } catch (e) {
      setSyncResult({ status: 'error', detail: e.message });
    }
    setSyncing(false);
  };

  return (
    <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 16, marginTop: 32 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, background: 'none',
          border: 'none', cursor: 'pointer', padding: 0, color: C.dim,
        }}>
        <span style={{ fontSize: 10 }}>{open ? '\u25BC' : '\u25B6'}</span>
        <span style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
          Admin
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 16 }}>
          <div style={{
            background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: C.muted, margin: 0 }}>Contact Sync</h3>
              <button onClick={handleSync} disabled={syncing}
                style={{
                  fontSize: 12, padding: '6px 12px', borderRadius: 6,
                  border: `1px solid ${C.accent}44`, cursor: syncing ? 'default' : 'pointer',
                  background: syncing ? 'transparent' : C.accent + '18',
                  color: C.accent, opacity: syncing ? 0.6 : 1,
                }}>
                {syncing ? 'Syncing...' : 'Sync Contacts from Networking App'}
              </button>
            </div>
            <p style={{ fontSize: 12, color: C.dim, marginBottom: 12 }}>
              Pull contacts from the Networking App into unified_contacts. Matches by name, syncs
              relationship labels, and builds relational aliases for entity resolution.
            </p>

            {syncResult && (
              <div style={{
                padding: '10px 14px', borderRadius: 6, fontSize: 13,
                background: syncResult.status === 'ok' ? C.green + '12' : C.red + '12',
                border: `1px solid ${syncResult.status === 'ok' ? C.green + '33' : C.red + '33'}`,
                color: syncResult.status === 'ok' ? C.green : C.red,
              }}>
                {syncResult.status === 'ok' ? (
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: 2 }}>Sync complete</div>
                    <div style={{ fontSize: 12 }}>
                      {syncResult.total_fetched || 0} fetched &middot; {syncResult.matched || 0} matched &middot; {syncResult.created || 0} created &middot; {syncResult.skipped || 0} skipped
                    </div>
                  </div>
                ) : (
                  <span>Error: {syncResult.detail || 'Unknown error'}</span>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
