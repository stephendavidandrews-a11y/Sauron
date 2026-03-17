import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { api } from '../api';
import { relativeTime } from "../utils/time";

// ─── Utilities ───────────────────────────────────────────────────────────────

function formatDuration(seconds) {
  if (!seconds) return '';
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)}min`;
}

function parseRelationships(raw) {
  if (!raw) return null;
  if (typeof raw === 'object') return raw;
  try { return JSON.parse(raw); } catch { return null; }
}

function pickOneLiner(brief) {
  // Most important thing: most recent what_changed, else highest-confidence belief
  if (brief.what_changed?.length > 0) {
    const item = brief.what_changed[0];
    return { text: item.belief_summary, type: 'changed' };
  }
  if (brief.beliefs?.length > 0) {
    const sorted = [...brief.beliefs].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    return { text: sorted[0].belief_summary, type: 'belief' };
  }
  return null;
}

// ─── Status / Type Chip Helpers ──────────────────────────────────────────────

const BELIEF_STATUS_STYLES = {
  active:       'bg-success/20 text-success',
  refined:      'bg-success/20 text-success',
  provisional:  'bg-warning/20 text-warning',
  qualified:    'bg-warning/20 text-warning',
  time_bounded: 'bg-warning/20 text-warning',
  contested:    'bg-danger/20 text-danger',
  stale:        'bg-border text-text-dim',
  under_review: 'bg-orange-500/20 text-orange-400',
};

const BELIEF_STATUS_LABELS = {
  active: 'solid', refined: 'solid',
  provisional: 'shifting', qualified: 'shifting', time_bounded: 'shifting',
  contested: 'contested', stale: 'stale', under_review: 'review',
};

const CLAIM_TYPE_STYLES = {
  fact:         'bg-accent/20 text-accent',
  position:     'bg-purple/20 text-purple',
  commitment:   'bg-warning/20 text-warning',
  preference:   'bg-success/20 text-success',
  relationship: 'bg-pink-500/20 text-pink-400',
  observation:  'bg-border text-text-dim',
  tactical:     'bg-orange-500/20 text-orange-400',
};

function BeliefStatusChip({ status }) {
  const cls = BELIEF_STATUS_STYLES[status] || 'bg-border text-text-dim';
  const label = BELIEF_STATUS_LABELS[status] || status;
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${cls}`}>
      {label}
    </span>
  );
}

function ClaimTypeBadge({ type }) {
  const cls = CLAIM_TYPE_STYLES[type] || 'bg-border text-text-dim';
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${cls}`}>
      {type}
    </span>
  );
}

// ─── Expandable Module ───────────────────────────────────────────────────────

function ExpandableModule({ title, count, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3
                   bg-transparent border-0 cursor-pointer text-left
                   hover:bg-card-hover transition-colors"
      >
        <span className="text-sm font-semibold text-text-muted uppercase tracking-wide">
          {title}
          {count != null && (
            <span className="ml-2 text-text-dim font-normal normal-case">({count})</span>
          )}
        </span>
        <span className="text-text-dim text-xs">{open ? '-- Collapse' : '+ Expand'}</span>
      </button>
      {open && <div className="px-5 pb-4">{children}</div>}
    </div>
  );
}

// ─── 3-Second Skim ───────────────────────────────────────────────────────────

function ThreeSecondSkim({ brief }) {
  const contact = brief.contact || {};
  const rel = parseRelationships(contact.relationships);
  const oneLiner = pickOneLiner(brief);

  const contextParts = [];
  if (rel?.personal_ring || rel?.personalRing) {
    contextParts.push(rel.personal_ring || rel.personalRing);
  }
  if (rel?.howWeMet || rel?.how_we_met) {
    contextParts.push(`met ${rel.howWeMet || rel.how_we_met}`);
  }
  if (contact.email) {
    contextParts.push(contact.email);
  }

  return (
    <div className="bg-card border border-border rounded-lg p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-bold text-text truncate">
            {contact.canonical_name || 'Unknown'}
          </h2>
          {contextParts.length > 0 && (
            <p className="text-sm text-text-muted mt-0.5 truncate">
              {contextParts.join(' \u00b7 ')}
            </p>
          )}
        </div>
        <div className="text-right shrink-0">
          <div className="text-xs text-text-dim">
            {brief.last_interaction ? relativeTime(brief.last_interaction) : 'no history'}
          </div>
          <div className="text-xs text-text-muted mt-0.5">
            {brief.interaction_count || 0} interaction{brief.interaction_count !== 1 ? 's' : ''}
          </div>
        </div>
      </div>
      {oneLiner && (
        <p className="text-sm text-text-dim mt-3 border-t border-border pt-3">
          <span className="text-text-muted mr-1">
            {oneLiner.type === 'changed' ? 'Changed:' : 'Key:'}
          </span>
          {oneLiner.text?.slice(0, 160)}
        </p>
      )}
    </div>
  );
}

// ─── 15-Second Skim ──────────────────────────────────────────────────────────

function FifteenSecondSkim({ brief }) {
  const interactions = brief.recent_interactions || [];
  const commitments = brief.commitments || [];
  const beliefs = brief.beliefs || [];
  const whatChanged = brief.what_changed || [];

  // Split commitments into "I owe" vs "They owe"
  const contactName = brief.contact?.canonical_name?.toLowerCase() || '';
  const iOwe = commitments.filter(c =>
    c.subject_name && c.subject_name.toLowerCase() !== contactName
  ).slice(0, 3);
  const theyOwe = commitments.filter(c =>
    !c.subject_name || c.subject_name.toLowerCase() === contactName
  ).slice(0, 3);

  const topBeliefs = [...beliefs]
    .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
    .slice(0, 5);

  const hasContent = interactions.length > 0 || commitments.length > 0
    || beliefs.length > 0 || whatChanged.length > 0;

  if (!hasContent) return null;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Recent interactions */}
      {interactions.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-3">
            Recent Interactions
          </h3>
          <ul className="space-y-2">
            {interactions.slice(0, 5).map((ix, i) => (
              <li key={ix.id || i} className="flex items-center justify-between text-sm">
                <Link
                  to={`/review/${ix.id}`}
                  className="text-text hover:text-accent transition-colors truncate mr-2"
                >
                  {ix.source || 'conversation'}
                  {ix.duration_seconds ? ` \u2014 ${formatDuration(ix.duration_seconds)}` : ''}
                </Link>
                <span className="text-xs text-text-dim shrink-0">
                  {relativeTime(ix.captured_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Commitments */}
      {commitments.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-3">
            Active Commitments
          </h3>
          {theyOwe.length > 0 && (
            <div className="mb-3">
              <p className="text-xs text-text-dim mb-1.5">They owe:</p>
              <ul className="space-y-1.5">
                {theyOwe.map((c, i) => (
                  <li key={i} className="text-sm text-text pl-2 border-l-2 border-warning/40">
                    {c.claim_text?.slice(0, 100)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {iOwe.length > 0 && (
            <div>
              <p className="text-xs text-text-dim mb-1.5">I owe:</p>
              <ul className="space-y-1.5">
                {iOwe.map((c, i) => (
                  <li key={i} className="text-sm text-text pl-2 border-l-2 border-accent/40">
                    {c.claim_text?.slice(0, 100)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Current beliefs */}
      {topBeliefs.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-3">
            Current Beliefs
          </h3>
          <ul className="space-y-2">
            {topBeliefs.map((b, i) => (
              <li key={i} className="text-sm flex items-start gap-2">
                <BeliefStatusChip status={b.status} />
                <span className="text-text leading-snug">
                  {b.belief_summary?.slice(0, 120) || b.belief_key}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* What changed */}
      {whatChanged.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-3">
            What Changed
          </h3>
          <ul className="space-y-2">
            {whatChanged.map((w, i) => (
              <li key={i} className="text-sm flex items-start gap-2">
                <span className="text-warning text-xs mt-0.5 shrink-0">&bull;</span>
                <div>
                  <span className="text-text">{w.belief_summary?.slice(0, 120)}</span>
                  {w.last_changed_at && (
                    <span className="text-text-dim text-xs ml-2">
                      {relativeTime(w.last_changed_at)}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ─── 2-Minute Deep Modules ──────────────────────────────────────────────────

function AllBeliefsModule({ beliefs }) {
  if (!beliefs?.length) return <p className="text-sm text-text-dim italic">No beliefs recorded.</p>;
  return (
    <ul className="space-y-2.5">
      {beliefs.map((b, i) => (
        <li key={i} className="text-sm flex items-start gap-2 pb-2 border-b border-border last:border-0">
          <BeliefStatusChip status={b.status} />
          <div className="flex-1 min-w-0">
            <div className="text-text">{b.belief_summary || b.belief_key}</div>
            <div className="flex items-center gap-3 mt-1 text-xs text-text-dim">
              {b.confidence != null && (
                <span>{(b.confidence * 100).toFixed(0)}% conf</span>
              )}
              {(b.support_count > 0 || b.contradiction_count > 0) && (
                <span>
                  <span className="text-success">{b.support_count || 0}</span>
                  {' / '}
                  <span className="text-danger">{b.contradiction_count || 0}</span>
                  {' evidence'}
                </span>
              )}
              {b.first_observed_at && (
                <span>since {relativeTime(b.first_observed_at)}</span>
              )}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function AllClaimsModule({ claims }) {
  if (!claims?.length) return <p className="text-sm text-text-dim italic">No recent claims.</p>;
  return (
    <ul className="space-y-2.5">
      {claims.map((c, i) => (
        <li key={i} className="text-sm pb-2 border-b border-border last:border-0">
          <div className="flex items-start gap-2">
            <ClaimTypeBadge type={c.claim_type} />
            <div className="flex-1 min-w-0">
              <div className="text-text">{c.claim_text?.slice(0, 200)}</div>
              <div className="flex items-center gap-3 mt-1 text-xs text-text-dim">
                {c.modality && <span>{c.modality}</span>}
                {c.confidence != null && (
                  <span>{(c.confidence * 100).toFixed(0)}%</span>
                )}
                {c.source && <span>{c.source}</span>}
                {c.captured_at && <span>{relativeTime(c.captured_at)}</span>}
              </div>
              {c.evidence_quote && (
                <p className="text-xs text-text-dim mt-1 italic border-l-2 border-border pl-2">
                  &ldquo;{c.evidence_quote.slice(0, 150)}&rdquo;
                </p>
              )}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function InteractionHistoryModule({ interactions }) {
  if (!interactions?.length) return <p className="text-sm text-text-dim italic">No interactions recorded.</p>;
  return (
    <ul className="space-y-1.5">
      {interactions.map((ix, i) => (
        <li key={ix.id || i} className="text-sm flex items-center justify-between">
          <Link
            to={`/review/${ix.id}`}
            className="text-text hover:text-accent transition-colors"
          >
            {ix.source || 'conversation'}
            {ix.duration_seconds ? ` \u2014 ${formatDuration(ix.duration_seconds)}` : ''}
          </Link>
          <span className="text-xs text-text-dim">
            {ix.captured_at ? relativeTime(ix.captured_at) : ''}
          </span>
        </li>
      ))}
    </ul>
  );
}

function GraphConnectionsModule({ connections }) {
  if (!connections?.length) return <p className="text-sm text-text-dim italic">No graph connections.</p>;
  return (
    <ul className="space-y-1.5">
      {connections.map((g, i) => (
        <li key={i} className="text-sm flex items-center gap-2">
          <span className="text-text">{g.from_entity}</span>
          <span className="text-text-dim text-xs px-1.5 py-0.5 rounded bg-border">
            {g.edge_type}
          </span>
          <span className="text-text">{g.to_entity}</span>
          {g.strength != null && (
            <span className="text-text-dim text-xs ml-auto">
              {typeof g.strength === 'number' ? g.strength.toFixed(2) : g.strength}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function RelationshipDataModule({ contact }) {
  const rel = parseRelationships(contact?.relationships);
  if (!rel) return <p className="text-sm text-text-dim italic">No relationship data.</p>;

  const entries = Object.entries(rel).filter(([, v]) =>
    v != null && v !== '' && !(Array.isArray(v) && v.length === 0)
  );

  if (entries.length === 0) {
    return <p className="text-sm text-text-dim italic">No relationship data.</p>;
  }

  return (
    <dl className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-start gap-3 text-sm">
          <dt className="text-text-muted w-32 shrink-0 capitalize">
            {key.replace(/([A-Z])/g, ' $1').replace(/_/g, ' ').trim()}
          </dt>
          <dd className="text-text">
            {Array.isArray(value) ? value.join(', ') : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// ─── Person Brief (full view) ────────────────────────────────────────────────

function PersonBrief({ brief, onBack }) {
  const isEmpty = !brief.beliefs?.length && !brief.recent_claims?.length
    && !brief.commitments?.length && (brief.interaction_count || 0) === 0;

  return (
    <div className="space-y-4">
      {/* Back button */}
      <button
        onClick={onBack}
        className="text-sm text-text-dim hover:text-text-muted transition-colors
                   cursor-pointer bg-transparent border-0 p-0"
      >
        &larr; Back
      </button>

      {/* 3-second skim */}
      <ThreeSecondSkim brief={brief} />

      {/* Empty state */}
      {isEmpty && (
        <div className="bg-card border border-border rounded-lg p-5 text-center">
          <p className="text-sm text-text-dim italic">
            Limited history available.
            {brief.last_interaction && (
              <span>
                {' '}Last interaction {relativeTime(brief.last_interaction)}.
              </span>
            )}
          </p>
          {brief.graph_connections?.length > 0 && (
            <p className="text-xs text-text-dim mt-2">
              Linked to {brief.graph_connections.length} topic{brief.graph_connections.length !== 1 ? 's' : ''} in the graph.
            </p>
          )}
        </div>
      )}

      {/* 15-second skim */}
      {!isEmpty && <FifteenSecondSkim brief={brief} />}

      {/* 2-minute expandable modules */}
      {!isEmpty && (
        <div className="space-y-3">
          {brief.beliefs?.length > 0 && (
            <ExpandableModule title="All Beliefs" count={brief.beliefs.length}>
              <AllBeliefsModule beliefs={brief.beliefs} />
            </ExpandableModule>
          )}

          {brief.recent_claims?.length > 0 && (
            <ExpandableModule title="All Claims" count={brief.recent_claims.length}>
              <AllClaimsModule claims={brief.recent_claims} />
            </ExpandableModule>
          )}

          {brief.recent_interactions?.length > 0 && (
            <ExpandableModule title="Interaction History" count={brief.recent_interactions.length}>
              <InteractionHistoryModule interactions={brief.recent_interactions} />
            </ExpandableModule>
          )}

          {brief.graph_connections?.length > 0 && (
            <ExpandableModule title="Graph Connections" count={brief.graph_connections.length}>
              <GraphConnectionsModule connections={brief.graph_connections} />
            </ExpandableModule>
          )}

          <ExpandableModule title="Relationship Data">
            <RelationshipDataModule contact={brief.contact} />
          </ExpandableModule>
        </div>
      )}
    </div>
  );
}

// ─── Autocomplete Dropdown ───────────────────────────────────────────────────

function AutocompleteDropdown({ results, onSelect, visible }) {
  if (!visible || !results?.length) return null;

  return (
    <div className="absolute z-50 top-full left-0 right-0 mt-1
                    bg-card border border-border rounded-lg shadow-lg
                    max-h-64 overflow-y-auto">
      {results.map((contact) => (
        <button
          key={contact.id}
          onClick={() => onSelect(contact)}
          className="w-full text-left px-4 py-2.5 bg-transparent border-0
                     hover:bg-card-hover transition-colors cursor-pointer
                     border-b border-border last:border-0"
        >
          <div className="text-sm text-text">{contact.canonical_name}</div>
          {contact.email && (
            <div className="text-xs text-text-dim mt-0.5">{contact.email}</div>
          )}
          {contact.aliases && (
            <div className="text-xs text-text-dim mt-0.5">
              aka {contact.aliases}
            </div>
          )}
        </button>
      ))}
    </div>
  );
}

// ─── Main Prep Page ──────────────────────────────────────────────────────────

export default function Prep() {
  const { query: urlQuery } = useParams();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const dropdownRef = useRef(null);
  const debounceRef = useRef(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [autocompleteResults, setAutocompleteResults] = useState([]);
  const [showAutocomplete, setShowAutocomplete] = useState(false);

  // Brief state
  const [brief, setBrief] = useState(null);
  const requestIdRef = useRef(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Focus input on mount (when not viewing a person)
  useEffect(() => {
    if (!brief && !urlQuery) {
      inputRef.current?.focus();
    }
  }, [brief, urlQuery]);

  // Handle URL query param: load person brief by name
  useEffect(() => {
    if (urlQuery) {
      const decoded = decodeURIComponent(urlQuery);
      setSearchQuery(decoded);
      loadBriefByName(decoded);
    }
  }, [urlQuery]);

  // Close autocomplete on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowAutocomplete(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Debounced autocomplete search
  const handleInputChange = useCallback((value) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (value.trim().length < 2) {
      setAutocompleteResults([]);
      setShowAutocomplete(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      try {
        const results = await api.searchContacts(value.trim(), 8);
        const contacts = Array.isArray(results) ? results : results?.contacts || [];
        setAutocompleteResults(contacts);
        setShowAutocomplete(contacts.length > 0);
      } catch {
        setAutocompleteResults([]);
        setShowAutocomplete(false);
      }
    }, 300);
  }, []);

  // Load brief by contact ID
  const loadBriefById = useCallback(async (contactId) => {
    const reqId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    setShowAutocomplete(false);
    try {
      const data = await api.personBrief(contactId);
      if (reqId !== requestIdRef.current) return; // stale request
      setBrief(data);
    } catch (err) {
      // Fallback: try to assemble from existing endpoints
      try {
        const fallback = await assembleFallbackBrief(contactId);
        setBrief(fallback);
      } catch {
        setError('Could not load person brief.');
        setBrief(null);
      }
    }
    setLoading(false);
  }, []);

  // Load brief by name (URL param or Enter key)
  const loadBriefByName = useCallback(async (name) => {
    const reqId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    setShowAutocomplete(false);
    try {
      const data = await api.personBriefByName(name);
      if (reqId !== requestIdRef.current) return; // stale request
      setBrief(data);
    } catch {
      // Fallback: search contacts, pick best match, assemble from existing APIs
      try {
        const results = await api.searchContacts(name, 1);
        const contacts = Array.isArray(results) ? results : results?.contacts || [];
        if (contacts.length > 0) {
          const fallback = await assembleFallbackBrief(contacts[0].id, contacts[0]);
          setBrief(fallback);
        } else {
          setError(`No contact found matching "${name}".`);
          setBrief(null);
        }
      } catch {
        setError('Could not load person brief.');
        setBrief(null);
      }
    }
    setLoading(false);
  }, []);

  // Assemble a brief from existing endpoints when /brief/person/ is not yet implemented
  async function assembleFallbackBrief(contactId, contactData = null) {
    const [beliefsRes, changedRes] = await Promise.allSettled([
      api.beliefsByContact(contactId, 50),
      api.whatChanged('person', contactId, 60),
    ]);

    const beliefs = beliefsRes.status === 'fulfilled'
      ? (Array.isArray(beliefsRes.value) ? beliefsRes.value : beliefsRes.value?.beliefs || [])
      : [];
    const whatChanged = changedRes.status === 'fulfilled'
      ? (Array.isArray(changedRes.value) ? changedRes.value : changedRes.value?.changes || [])
      : [];

    // If we don't have contact data, fetch it
    let contact = contactData;
    if (!contact) {
      try {
        const results = await api.searchContacts(contactId, 1);
        const contacts = Array.isArray(results) ? results : results?.contacts || [];
        contact = contacts[0] || { id: contactId, canonical_name: contactId };
      } catch {
        contact = { id: contactId, canonical_name: contactId };
      }
    }

    return {
      contact,
      beliefs,
      recent_claims: [],
      commitments: [],
      recent_interactions: [],
      graph_connections: [],
      interaction_count: 0,
      last_interaction: null,
      relationship_data: parseRelationships(contact?.relationships),
      what_changed: whatChanged,
    };
  }

  // Select from autocomplete
  const handleSelectContact = (contact) => {
    setSearchQuery(contact.canonical_name);
    setShowAutocomplete(false);
    navigate(`/prep/${encodeURIComponent(contact.canonical_name)}`, { replace: true });
    loadBriefById(contact.id);
  };

  // Enter key: navigate to URL and trigger name search
  const handleSubmit = (e) => {
    e.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;
    setShowAutocomplete(false);
    navigate(`/prep/${encodeURIComponent(q)}`, { replace: true });
    loadBriefByName(q);
  };

  // Back from brief view
  const handleBack = () => {
    setBrief(null);
    setError(null);
    setSearchQuery('');
    navigate('/prep', { replace: true });
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  return (
    <div className="py-6 space-y-6">
      <h1 className="text-2xl font-bold text-text">Prep</h1>

      {/* Launcher input - hidden when viewing a brief */}
      {!brief && !loading && (
        <div className="relative" ref={dropdownRef}>
          <form onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => handleInputChange(e.target.value)}
              onFocus={() => {
                if (autocompleteResults.length > 0) setShowAutocomplete(true);
              }}
              placeholder="Type a person's name..."
              className="w-full px-4 py-3 bg-card border border-border rounded-lg text-text
                         placeholder:text-text-dim outline-none focus:border-accent transition-colors"
              autoComplete="off"
            />
          </form>
          <AutocompleteDropdown
            results={autocompleteResults}
            onSelect={handleSelectContact}
            visible={showAutocomplete}
          />
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="text-center text-text-dim py-12">
          Loading brief...
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="bg-card border border-border rounded-lg p-5 text-center">
          <p className="text-sm text-text-dim">{error}</p>
          <button
            onClick={handleBack}
            className="mt-3 text-sm text-accent hover:text-accent-hover transition-colors
                       cursor-pointer bg-transparent border-0"
          >
            Try another search
          </button>
        </div>
      )}

      {/* Person brief */}
      {brief && !loading && (
        <PersonBrief brief={brief} onBack={handleBack} />
      )}

      {/* Empty state - no search, no brief */}
      {!brief && !loading && !error && !searchQuery && (
        <div className="text-center py-12 text-text-dim">
          <p className="text-lg mb-2">Type a name to pull up a person brief.</p>
          <p className="text-sm">3 seconds to skim, 15 seconds to prep, 2 minutes for full depth.</p>
        </div>
      )}
    </div>
  );
}
