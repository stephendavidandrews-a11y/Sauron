import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api';

export const C = {
  bg: '#0a0f1a', card: '#111827', cardHover: '#1a2234',
  border: '#1f2937', borderLight: '#374151', text: '#e5e7eb',
  textMuted: '#9ca3af', textDim: '#6b7280', accent: '#3b82f6',
  success: '#10b981', warning: '#f59e0b', danger: '#ef4444', purple: '#8b5cf6',
  amber: '#d97706',
};
export const cardStyle = { background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20 };

export const claimTypeColors = {
  fact: C.accent, position: C.purple, commitment: C.warning,
  preference: C.success, relationship: '#ec4899', observation: C.textMuted, tactical: '#f97316',
};

export const errorTypes = [
  { value: 'hallucinated_claim', label: 'Not real / hallucinated' },
  { value: 'wrong_claim_type', label: 'Wrong type' },
  { value: 'wrong_modality', label: 'Wrong modality' },
  { value: 'wrong_polarity', label: 'Wrong polarity' },
  { value: 'wrong_confidence', label: 'Confidence too high/low' },
  { value: 'bad_commitment_extraction', label: 'Bad commitment' },
  { value: 'overstated_position', label: 'Overstated position' },
  { value: 'bad_entity_linking', label: 'Wrong person/entity' },
  { value: 'wrong_stability', label: 'Wrong stability' },
];

export default function ConversationDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('episodes');
  const [reprocessing, setReprocessing] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [reviewStats, setReviewStats] = useState(null);
  const [contactsList, setContactsList] = useState([]);
  const [showReassignModal, setShowReassignModal] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [peopleStatus, setPeopleStatus] = useState(null);
  const [claims, setClaims] = useState([]);

  const reload = useCallback(() => {
    setLoading(true);
    setRefreshKey(k => k + 1);
    api.conversation(id).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    reload();
    api.contacts(500).then(d => setContactsList(d.contacts || [])).catch(() => {});
  }, [id]);

  // Sync claims from data load
  useEffect(() => {
    if (data?.claims) setClaims(data.claims);
  }, [data]);

  // Optimistic update helpers
  const updateClaim = useCallback((claimId, updates) => {
    setClaims(prev => prev.map(c => c.id === claimId ? { ...c, ...updates } : c));
  }, []);
  const addClaimToState = useCallback((newClaim) => {
    setClaims(prev => [...prev, newClaim]);
  }, []);

  const handleReprocess = async () => {
    setReprocessing(true);
    try {
      await api.pipelineProcess(id);
      setTimeout(() => { reload(); setReprocessing(false); }, 2000);
    } catch { setReprocessing(false); }
  };

  const handleMarkReviewed = async () => {
    setReviewing(true);
    try {
      const result = await api.markReviewed(id);
      setReviewed(true);
      if (result.stats) {
        setReviewStats(result.stats);
      }
    } catch (e) { console.error('Review failed', e); }
    setReviewing(false);
  };

  const [discarding, setDiscarding] = useState(false);
  const handleDiscard = async () => {
    if (!window.confirm('Discard this conversation? It will be removed from all review queues.')) return;
    setDiscarding(true);
    try {
      await api.discardConversation(id, 'discarded_from_review');
      window.location.href = '/review';
    } catch (e) {
      console.error('Failed to discard:', e);
      setDiscarding(false);
    }
  };

  if (loading) return <div style={{ color: C.textDim, padding: 40 }}>Loading...</div>;
  if (error) return (
    <div>
      <Link to="/review" style={{ color: C.accent, fontSize: 13 }}>{'\u2190'} Back</Link>
      <div style={{ ...cardStyle, marginTop: 16, borderColor: C.danger }}>
        <span style={{ color: C.danger }}>Error: {error}</span>
      </div>
    </div>
  );

  const convo = data?.conversation || {};
  const transcript = data?.transcript || [];
  const extraction = data?.extraction || null;
  const episodes = data?.episodes || [];
  const _rawClaims = data?.claims || [];  // raw from API, claims state is the live copy
  const beliefUpdates = data?.belief_updates || [];
  const isReviewed = reviewed || !!convo.reviewed_at;

  let parsedExtraction = null;
  if (extraction) {
    try { parsedExtraction = typeof extraction === 'string' ? JSON.parse(extraction) : extraction; }
    catch { parsedExtraction = extraction; }
  }
  const synthesis = parsedExtraction?.synthesis || parsedExtraction || {};

  // Collect unique entities linked in this conversation for the reassign dropdown
  // Sources: event_claims.subject_entity_id, claim_entities[], transcript speaker_ids
  const linkedEntities = {};
  claims.forEach(c => {
    // From subject_entity_id (backward compat)
    if (c.subject_entity_id && (c.linked_entity_name || c.subject_name)) {
      linkedEntities[c.subject_entity_id] = c.linked_entity_name || c.subject_name;
    }
    // From claim_entities junction table
    if (c.entities && c.entities.length > 0) {
      c.entities.forEach(ent => {
        if (ent.entity_id && ent.entity_name) {
          linkedEntities[ent.entity_id] = ent.entity_name;
        }
      });
    }
  });
  // From transcript speaker_ids
  transcript.forEach(seg => {
    if (seg.speaker_id && seg.speaker_name) {
      linkedEntities[seg.speaker_id] = seg.speaker_name;
    }
  });

  const tabs = [
    { key: 'episodes', label: `Episodes (${episodes.length})` },
    { key: 'transcript', label: `Transcript (${transcript.length})` },
    { key: 'claims', label: `Claims (${claims.length})` },
    { key: 'summary', label: 'Summary' },
    { key: 'raw', label: 'Raw' },
  ];

  return (
    <div className="py-4" data-testid="conversation-detail">
      <Link to="/review" className="text-accent text-sm no-underline">{'\u2190'} Back to review</Link>
      <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 className="text-xl font-bold text-text">{convo.manual_note || convo.title || convo.source || 'Conversation'}</h1>
          <p className="text-sm text-text-dim mt-1">
            {convo.source || 'unknown'} &middot; {(convo.captured_at || convo.created_at)?.slice(0, 10) || ''} &middot; {convo.processing_status || ''}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {/* Reassign Speaker button */}
          {Object.keys(linkedEntities).length > 0 && (
            <button onClick={() => setShowReassignModal(true)} data-testid="reassign-speaker-btn"
              style={{ padding: '8px 16px', background: `${C.amber}22`, color: C.amber,
                border: `1px solid ${C.amber}44`, borderRadius: 6, fontSize: 13, cursor: 'pointer', fontWeight: 500 }}>
              Reassign Speaker
            </button>
          )}

          {(convo.processing_status === 'completed' || convo.processing_status === 'awaiting_claim_review') && !isReviewed && (<>
            <button onClick={handleDiscard} disabled={discarding} data-testid="discard-btn"
              style={{ padding: '6px 14px', background: 'transparent', color: '#ef4444',
                border: '1px solid #ef444444', borderRadius: 6, fontSize: 12, cursor: 'pointer',
                opacity: discarding ? 0.7 : 1 }}>
              {discarding ? 'Discarding...' : '✗ Discard'}
            </button>
            <button onClick={handleMarkReviewed} disabled={reviewing} data-testid="mark-reviewed-btn"
              style={{ padding: '8px 16px', background: C.success, color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer', opacity: reviewing ? 0.7 : 1 }}>
              {reviewing ? 'Reviewing...' : (<>
                {'✓ Mark as Reviewed'}
                {peopleStatus && (peopleStatus.yellow + peopleStatus.red) > 0 && (
                  <span style={{ marginLeft: 8, fontSize: 11, opacity: 0.8 }}>
                    ({peopleStatus.yellow + peopleStatus.red} unconfirmed)
                  </span>
                )}
              </>)}
            </button>
          </>)}
          {isReviewed && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span data-testid="reviewed-badge" style={{ padding: '8px 16px', background: `${C.success}22`, color: C.success, borderRadius: 6, fontSize: 13, fontWeight: 600 }}>
                {'✓'} Reviewed
              </span>
              {reviewStats && (
                <span style={{ fontSize: 12, color: C.textDim }}>
                  {reviewStats.approved} approved
                  {reviewStats.corrections > 0 && <> &middot; {reviewStats.corrections} corrected</>}
                  {reviewStats.dismissed > 0 && <> &middot; {reviewStats.dismissed} dismissed</>}
                  {reviewStats.beliefs_affected > 0 && (
                    <> &middot; <span style={{ color: C.warning }}>{reviewStats.beliefs_affected} beliefs affected</span></>
                  )}
                </span>
              )}
            </div>
          )}
          {convo.processing_status === 'awaiting_speaker_review' && (
            <Link to={`/review/${convo.id}/speakers`}
              style={{ padding: '8px 16px', background: '#a78bfa', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer', textDecoration: 'none', fontWeight: 500 }}>
              Confirm Speakers
            </Link>
          )}
          {(convo.processing_status === 'error' || convo.processing_status === 'pending') && (
            <button onClick={handleReprocess} disabled={reprocessing} data-testid="reprocess-btn"
              style={{ padding: '8px 16px', background: C.accent, color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer', opacity: reprocessing ? 0.7 : 1 }}>
              {reprocessing ? 'Processing...' : 'Reprocess'}
            </button>
          )}
        </div>
      </div>

      {/* Metadata chips */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0 20px' }}>
        {convo.duration_seconds && <Chip label="Duration" value={`${Math.round(convo.duration_seconds / 60)}m`} />}
        {convo.context_classification && <Chip label="Context" value={convo.context_classification} />}
        {synthesis.word_voice_alignment && (
          <Chip label="Voice" value={synthesis.word_voice_alignment}
            color={synthesis.word_voice_alignment === 'misaligned' ? C.danger : C.success} />
        )}
      </div>

      {/* Layer 1: People resolution */}
      <PeopleReviewBanner key={`people-${refreshKey}`} conversationId={id} contacts={contactsList} onResolved={reload} onPeopleLoaded={setPeopleStatus} />

      {/* Layer 2: Relational references (unchanged) */}
      <RelationalReferencesBanner key={`rel-${refreshKey}`} conversationId={id} contacts={contactsList} onResolved={reload} />

      {/* Layer 3: Routing preview */}
      <RoutingPreview key={`routing-${refreshKey}`} conversationId={id} refreshKey={refreshKey} />

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} data-testid={`tab-${t.key}`}
            style={{ padding: '8px 16px', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer', fontWeight: 500,
              background: tab === t.key ? C.accent : C.card, color: tab === t.key ? '#fff' : C.textMuted }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'episodes' && <EpisodesTab episodes={episodes} claims={claims} conversationId={id} contacts={contactsList} updateClaim={updateClaim} addClaimToState={addClaimToState} />}
      {tab === 'transcript' && <TranscriptTab transcript={transcript} conversationId={id} contacts={contactsList} />}
      {tab === 'claims' && <ClaimsTab claims={claims} conversationId={id} contacts={contactsList} updateClaim={updateClaim} />}
      {tab === 'summary' && <SummaryTab synthesis={synthesis} beliefUpdates={beliefUpdates} claims={claims} />}
      {tab === 'raw' && <RawTab extraction={parsedExtraction} />}

      {/* Bulk Reassignment Modal */}
      {showReassignModal && (
        <BulkReassignModal
          conversationId={id}
          linkedEntities={linkedEntities}
          contacts={contactsList}
          onClose={() => setShowReassignModal(false)}
          onComplete={() => { setShowReassignModal(false); reload(); }}
          onSwitchTab={setTab}
        />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// BULK REASSIGNMENT MODAL
// ═══════════════════════════════════════════════════════
export function BulkReassignModal({
  conversationId, linkedEntities, contacts, onClose, onComplete, onSwitchTab,
  searchContactsFn = api.searchContacts,
  bulkReassignFn = api.bulkReassign,
  initialPreview, initialResult,
}) {
  const [fromEntityId, setFromEntityId] = useState('');
  const [toEntityId, setToEntityId] = useState('');
  const [scope, setScope] = useState('all');
  const [toSearch, setToSearch] = useState('');
  const [toResults, setToResults] = useState([]);
  const [preview, setPreview] = useState(initialPreview || null);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(initialResult || null);
  const [error, setError] = useState(null);
  const [nameOverride, setNameOverride] = useState('');

  const handleSearchTo = async (q) => {
    setToSearch(q);
    if (q.length < 2) { setToResults([]); return; }
    try {
      const r = await searchContactsFn(q, 10);
      setToResults(r.filter(c => c.is_confirmed !== 0));
    } catch {
      setToResults(contacts.filter(c => c.is_confirmed !== 0 && c.canonical_name.toLowerCase().includes(q.toLowerCase())).slice(0, 10));
    }
  };

  const handlePreview = async () => {
    if (!fromEntityId || !toEntityId) return;
    setError(null);
    try {
      const p = await bulkReassignFn(conversationId, fromEntityId, toEntityId, scope, true);
      setPreview(p);
    } catch (e) {
      setError(e.message);
    }
  };

  const handleExecute = async () => {
    if (!fromEntityId || !toEntityId) return;
    setExecuting(true);
    setError(null);
    try {
      const r = await bulkReassignFn(conversationId, fromEntityId, toEntityId, scope, false);
      setResult(r);
    } catch (e) {
      setError(e.message);
    }
    setExecuting(false);
  };

  const selectedToName = contacts.find(c => c.id === toEntityId)?.canonical_name || '';

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ ...cardStyle, width: 520, maxHeight: '80vh', overflow: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: C.text }}>Bulk Reassign Speaker</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.textDim, fontSize: 18, cursor: 'pointer' }}>&times;</button>
        </div>

        {result ? (
          <div>
            <div style={{ padding: 16, borderRadius: 6, background: `${C.success}15`, border: `1px solid ${C.success}33`, marginBottom: 16 }}>
              <p style={{ fontSize: 14, fontWeight: 600, color: C.success, marginBottom: 8 }}>Reassignment Complete</p>
              <p style={{ fontSize: 13, color: C.text }}>
                {result.from_entity} &rarr; {result.to_entity}
              </p>
              <div style={{ fontSize: 12, color: C.textMuted, marginTop: 8 }}>
                <p>{result.claims_updated} claims updated</p>
                <p>{result.transcripts_updated} transcript segments updated</p>
                <p>{result.beliefs_invalidated} beliefs set to under_review</p>
                {result.ambiguous_claims_flagged > 0 && (
                  <p style={{ color: C.amber }}>{result.ambiguous_claims_flagged} claims flagged as ambiguous</p>
                )}
              </div>
              {result.transcript_review_recommended && (
                <p style={{ fontSize: 12, color: C.warning, marginTop: 8 }}>
                  Transcript speaker labels were also updated. Review the Transcript tab to verify.
                </p>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {result.transcript_review_recommended && (
                <button onClick={() => { onComplete(); if (onSwitchTab) onSwitchTab('transcript'); }}
                  style={{ flex: 1, padding: '10px 16px', background: `${C.warning}22`, color: C.warning,
                    border: `1px solid ${C.warning}44`, borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                  Review Transcript
                </button>
              )}
              <button onClick={onComplete} style={{ flex: 1, padding: '10px 16px', background: C.accent, color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                Close & Refresh
              </button>
            </div>
          </div>
        ) : (
          <div>
            {/* From entity selector */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: C.textMuted, display: 'block', marginBottom: 6 }}>Reassign all references from:</label>
              <select value={fromEntityId} onChange={e => { setFromEntityId(e.target.value); setPreview(null); }}
                style={{ width: '100%', padding: '8px 10px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 13 }}>
                <option value="">Select entity...</option>
                {Object.entries(linkedEntities).map(([eId, eName]) => (
                  <option key={eId} value={eId}>{eName}</option>
                ))}
              </select>
            </div>

            {/* To entity selector */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: C.textMuted, display: 'block', marginBottom: 6 }}>Reassign to:</label>
              {toEntityId ? (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 13, color: C.text, padding: '8px 10px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, flex: 1 }}>
                    {selectedToName}
                  </span>
                  <button onClick={() => { setToEntityId(''); setToSearch(''); setPreview(null); }}
                    style={{ fontSize: 12, color: C.textDim, background: 'none', border: `1px solid ${C.border}`, borderRadius: 4, padding: '6px 10px', cursor: 'pointer' }}>
                    Change
                  </button>
                </div>
              ) : (
                <div>
                  <input value={toSearch} onChange={e => handleSearchTo(e.target.value)}
                    placeholder="Search contacts..."
                    style={{ width: '100%', padding: '8px 10px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 13, outline: 'none' }} />
                  {toResults.length > 0 && (
                    <div style={{ border: `1px solid ${C.border}`, borderRadius: 4, marginTop: 4, maxHeight: 160, overflow: 'auto', background: C.bg }}>
                      {toResults.map(c => (
                        <button key={c.id} onClick={() => { setToEntityId(c.id); setToResults([]); setToSearch(''); setPreview(null); }}
                          style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 10px', fontSize: 12, color: C.text, background: 'transparent', border: 'none', cursor: 'pointer' }}
                          onMouseEnter={e => e.target.style.background = C.cardHover}
                          onMouseLeave={e => e.target.style.background = 'transparent'}>
                          {c.canonical_name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Scope selector */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: C.textMuted, display: 'block', marginBottom: 6 }}>Scope:</label>
              <div style={{ display: 'flex', gap: 8 }}>
                {['all', 'claims_only', 'transcript_only'].map(s => (
                  <button key={s} onClick={() => { setScope(s); setPreview(null); }}
                    style={{ padding: '6px 12px', borderRadius: 4, fontSize: 12, cursor: 'pointer', border: 'none',
                      background: scope === s ? C.accent : `${C.accent}15`, color: scope === s ? '#fff' : C.textMuted }}>
                    {s === 'all' ? 'All' : s === 'claims_only' ? 'Claims only' : 'Transcript only'}
                  </button>
                ))}
              </div>
            </div>

            {/* Name override */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: C.textMuted, display: 'block', marginBottom: 6 }}>
                Display Name Override <span style={{ color: C.textDim, fontWeight: 400 }}>(optional)</span>
              </label>
              <input value={nameOverride} onChange={e => setNameOverride(e.target.value)}
                placeholder="Leave empty to use contact's canonical name"
                style={{ width: '100%', padding: '8px 10px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 13, outline: 'none' }} />
              <p style={{ fontSize: 11, color: C.textDim, marginTop: 4 }}>
                Override the name used in claim text replacement (e.g., correct a misspelling)
              </p>
            </div>

            {error && (
              <div style={{ padding: 10, borderRadius: 4, background: `${C.danger}15`, border: `1px solid ${C.danger}33`, color: C.danger, fontSize: 12, marginBottom: 16 }}>
                {error}
              </div>
            )}

            {/* Preview button */}
            {!preview && (
              <button onClick={handlePreview} disabled={!fromEntityId || !toEntityId}
                style={{ width: '100%', padding: '10px 16px', background: `${C.accent}22`, color: C.accent,
                  border: `1px solid ${C.accent}44`, borderRadius: 6, fontSize: 13, cursor: 'pointer',
                  opacity: (!fromEntityId || !toEntityId) ? 0.5 : 1 }}>
                Preview Changes
              </button>
            )}

            {/* Preview results */}
            {preview && (
              <div style={{ marginTop: 8 }}>
                <div style={{ padding: 12, borderRadius: 6, background: `${C.warning}10`, border: `1px solid ${C.warning}33`, marginBottom: 12 }}>
                  <p style={{ fontSize: 13, fontWeight: 600, color: C.warning, marginBottom: 4 }}>Preview: {preview.from_entity} &rarr; {preview.to_entity}</p>
                  <div style={{ fontSize: 12, color: C.textMuted }}>
                    <p>{preview.claims_affected} claims will be reassigned</p>
                    <p>{preview.transcript_segments_affected} transcript segments will be updated</p>
                    <p>{preview.belief_evidence_links_affected} belief evidence links affected</p>
                  </div>
                </div>

                {preview.sample_claims?.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <p style={{ fontSize: 11, color: C.textDim, marginBottom: 6, textTransform: 'uppercase', fontWeight: 600 }}>Sample changes:</p>
                    {preview.sample_claims.map((sc, i) => (
                      <div key={i} style={{ fontSize: 12, padding: '6px 0', borderBottom: `1px solid ${C.border}` }}>
                        <span style={{ color: C.danger, textDecoration: 'line-through' }}>{sc.old_subject}</span>
                        {' \u2192 '}
                        <span style={{ color: C.success }}>{sc.new_subject}</span>
                        <p style={{ color: C.textDim, marginTop: 2, fontSize: 11 }}>{sc.claim_text?.slice(0, 120)}</p>
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ display: 'flex', gap: 8 }}>
                  <button onClick={() => setPreview(null)}
                    style={{ flex: 1, padding: '10px 16px', background: 'transparent', color: C.textMuted,
                      border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                    Cancel
                  </button>
                  <button onClick={handleExecute} disabled={executing}
                    style={{ flex: 1, padding: '10px 16px', background: C.danger, color: '#fff',
                      border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer',
                      opacity: executing ? 0.7 : 1 }}>
                    {executing ? 'Executing...' : `Reassign ${preview.claims_affected} Claims`}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// EPISODES TAB — Primary Review Surface
// ═══════════════════════════════════════════════════════
export function EpisodesTab({ episodes: initialEpisodes, claims: initialClaims, conversationId, contacts, updateClaim, addClaimToState }) {
  const [episodes, setEpisodes] = useState(initialEpisodes);
  useEffect(() => { setEpisodes(initialEpisodes); }, [initialEpisodes]);
  const claims = initialClaims;  // Use lifted parent state directly
  const [addingClaimEpisode, setAddingClaimEpisode] = useState(null);  // episodeId or "__orphan__"
  const [expanded, setExpanded] = useState({});
  const [reviewedClaims, setReviewedClaims] = useState(() => {
    const set = new Set();
    (initialClaims || []).forEach(c => {
      if (c.review_status === 'user_confirmed' || c.review_status === 'user_corrected') set.add(c.id);
    });
    return set;
  });
  const [dismissed, setDismissed] = useState(() => {
    const d = {};
    (initialClaims || []).forEach(c => {
      if (c.review_status === 'dismissed') d[c.id] = 'hallucinated_claim';
    });
    return d;
  });
  const [deferred, setDeferred] = useState(() => {
    const d = new Set();
    (initialClaims || []).forEach(c => {
      if (c.review_status === 'deferred') d.add(c.id);
    });
    return d;
  });
  const [editingClaim, setEditingClaim] = useState(null);
  const [editText, setEditText] = useState('');
  const [relinkClaim, setRelinkClaim] = useState(null);
  const [relationshipPrompt, setRelationshipPrompt] = useState(null);  // claim ID showing re-link prompt after text edit

  const toggle = (epId) => setExpanded(prev => ({ ...prev, [epId]: !prev[epId] }));

  const handleBatchCorrect = (claimId, updatedClaim) => {
    updateClaim(claimId, { ...updatedClaim, review_status: 'user_corrected' });
    setReviewedClaims(prev => new Set(prev).add(claimId));
  };

  const claimsByEpisode = {};
  const orphanClaims = [];
  claims.forEach(c => {
    if (c.episode_id) {
      if (!claimsByEpisode[c.episode_id]) claimsByEpisode[c.episode_id] = [];
      claimsByEpisode[c.episode_id].push(c);
    } else {
      orphanClaims.push(c);
    }
  });

  const handleApprove = async (claimId) => {
    // Optimistic update
    updateClaim(claimId, { review_status: 'user_confirmed' });
    setReviewedClaims(prev => new Set(prev).add(claimId));
    try {
      await api.approveClaim(conversationId, claimId);
    } catch (e) {
      console.error('Approve failed', e);
      updateClaim(claimId, { review_status: 'unreviewed' });  // rollback
      setReviewedClaims(prev => { const s = new Set(prev); s.delete(claimId); return s; });
    }
  };

  const handleApproveAll = async (epId) => {
    const epClaims = claimsByEpisode[epId] || [];
    const claimIds = epClaims.map(c => c.id);
    try {
      await api.approveClaimsBulk(conversationId, claimIds);
      setReviewedClaims(prev => {
        const next = new Set(prev);
        epClaims.forEach(c => next.add(c.id));
        return next;
      });
      claimIds.forEach(cid => updateClaim(cid, { review_status: 'user_confirmed' }));
    } catch (e) {
      console.error('Approve all failed', e);
      setReviewedClaims(prev => {
        const next = new Set(prev);
        epClaims.forEach(c => next.add(c.id));
        return next;
      });
    }
  };

  const handleDismiss = async (claim, errorType) => {
    try {
      await api.dismissClaim(conversationId, claim.id, errorType, null);
      setDismissed(prev => ({ ...prev, [claim.id]: errorType }));
      updateClaim(claim.id, { review_status: 'dismissed' });
    } catch (e) { console.error('Flag failed', e); }
  };

  const handleDefer = async (claimId) => {
    // Optimistic update
    updateClaim(claimId, { review_status: 'deferred' });
    setDeferred(prev => new Set(prev).add(claimId));
    try {
      await api.deferClaim(conversationId, claimId);
    } catch (e) {
      console.error('Defer failed', e);
      updateClaim(claimId, { review_status: 'unreviewed' });  // rollback
      setDeferred(prev => { const s = new Set(prev); s.delete(claimId); return s; });
    }
  };

  const handleEdit = async (claim) => {
    try {
      await api.correctClaim(conversationId, claim.id, 'claim_text_edited', claim.claim_text, editText, null);
      updateClaim(claim.id, { claim_text: editText, review_status: 'user_corrected', text_user_edited: true });  // Update in-place for immediate UI feedback
      setEditingClaim(null);
      setRelinkClaim(claim.id);  // Show entity re-link prompt
    } catch (e) { console.error('Edit failed', e); }
  };

  const handleEntityLink = async (claim, contactId) => {
    try {
      const result = await api.linkEntity(conversationId, claim.id, contactId, claim.subject_name, null);
      const contact = contacts.find(c => c.id === contactId);
      const newName = contact ? contact.canonical_name : '';
      // Use entities list from backend response (source of truth)
      if (result && result.entities) {
        updateClaim(claim.id, {
          subject_entity_id: contactId, subject_name: newName,
          entities: result.entities,
        });
      } else {
        // Fallback: update immutably
        updateClaim(claim.id, {
          subject_entity_id: contactId, subject_name: newName,
        });
      }
      // If backend replaced ambiguous first-name refs with canonical name, update text
      if (result && result.text_updated && result.updated_text) {
        claim.claim_text = result.updated_text;
        claim.display_overrides = null;
      }
      // If backend detected a relational reference, prompt to save relationship
      if (result && result.relational_ref) {
        const ref = result.relational_ref;
        const linkedName = contact ? contact.canonical_name : '';
        const anchorContact = contacts.find(c => c.canonical_name === ref.anchor_name);
        if (anchorContact) {
          setRelationshipPrompt({
            anchorId: anchorContact.id,
            anchorName: ref.anchor_name,
            relationship: ref.relationship,
            targetId: contactId,
            targetName: linkedName,
            phrase: ref.phrase,
          });
        }
      }
    } catch (e) { console.error('Entity link failed', e); }
  };

  const handleRemoveEntity = async (claim, entityLinkId) => {
    try {
      await api.removeEntityLink(entityLinkId);
      if (claim.entities) {
        claim.entities = claim.entities.filter(e => e.id !== entityLinkId);
      }
      const subjectEntities = (claim.entities || []).filter(e => e.role === 'subject');
      const updates = { entities: [...(claim.entities || [])] };
      if (subjectEntities.length === 0) {
        updates.subject_entity_id = null;
        updates.subject_name = '';
      }
      updateClaim(claim.id, updates);
    } catch (e) { console.error('Remove entity link failed', e); }
  };

  if (episodes.length === 0) {
    return <div style={cardStyle}><p style={{ color: C.textDim, textAlign: 'center', padding: 30, fontSize: 13 }}>No episodes extracted.</p></div>;
  }

  const handleSaveRelationship = async () => {
    if (!relationshipPrompt) return;
    try {
      await api.saveRelationship(
        relationshipPrompt.anchorId,
        relationshipPrompt.relationship,
        relationshipPrompt.targetId,
        relationshipPrompt.targetName,
        relationshipPrompt.notes || undefined
      );
      setRelationshipPrompt(null);
    } catch (e) { console.error('Save relationship failed', e); }
  };


  const handleAddClaim = (createdClaim) => {
    addClaimToState(createdClaim);
    setAddingClaimEpisode(null);
  };

  const handleReassign = async (claimId, newEpisodeId) => {
    updateClaim(claimId, { episode_id: newEpisodeId });
    try {
      await api.reassignClaim(claimId, conversationId, newEpisodeId);
    } catch (e) {
      console.error('Reassign failed', e);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {relationshipPrompt && (
        <div style={{
          padding: '12px 16px', borderRadius: 6,
          background: '#ec4899' + '15', border: '1px solid ' + '#ec4899' + '44',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div>
            <span style={{ fontSize: 13, color: C.text }}>
              Save this relationship? </span>
            <strong style={{ color: '#ec4899' }}>
              {relationshipPrompt.anchorName} → {relationshipPrompt.relationship} → {relationshipPrompt.targetName}
            </strong>
            <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
              Detected from: "{relationshipPrompt.phrase}"
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={handleSaveRelationship} style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
            }}>Save</button>
            <button onClick={() => setRelationshipPrompt(null)} style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: C.card, color: C.textDim, border: '1px solid ' + C.border,
            }}>Skip</button>
          </div>
        </div>
      )}
      {episodes.map((ep, i) => {
        const epClaims = claimsByEpisode[ep.id] || [];
        const isExpanded = expanded[ep.id];
        const allReviewed = epClaims.length > 0 && epClaims.every(c => reviewedClaims.has(c.id) || dismissed[c.id]);
        return (
          <div key={ep.id || i} style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
            <div onClick={() => toggle(ep.id)} style={{
              padding: '14px 20px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10,
              borderLeft: `3px solid ${allReviewed ? C.success : C.accent}`,
            }}>
              <span style={{ fontSize: 12, color: C.textDim }}>{isExpanded ? '\u25BC' : '\u25B6'}</span>
              <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 3, fontWeight: 600,
                background: `${C.purple}22`, color: C.purple, textTransform: 'uppercase' }}>
                {ep.episode_type}
              </span>
              <span style={{ fontSize: 14, fontWeight: 500, color: C.text, flex: 1 }}>{ep.title}</span>
              <span style={{ fontSize: 12, color: C.textDim }}>{epClaims.length} claim{epClaims.length !== 1 ? 's' : ''}</span>
              {allReviewed && <span style={{ fontSize: 11, color: C.success }}>{'✓'}</span>}
            </div>

            {isExpanded && (
              <div style={{ padding: '0 20px 16px', borderTop: `1px solid ${C.border}` }}>
                {ep.summary && (
                  <p style={{ fontSize: 13, color: C.textMuted, lineHeight: 1.5, margin: '12px 0' }}>{ep.summary}</p>
                )}
                {(ep.start_time != null || ep.end_time != null) && (
                  <p style={{ fontSize: 11, color: C.textDim, margin: '0 0 12px' }}>
                    {ep.start_time != null ? `${Number(ep.start_time).toFixed(0)}s` : '?'} &ndash; {ep.end_time != null ? `${Number(ep.end_time).toFixed(0)}s` : '?'}
                  </p>
                )}

                {epClaims.length > 0 && (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: 'uppercase' }}>Claims</span>
                      {!allReviewed && (
                        <button onClick={(e) => { e.stopPropagation(); handleApproveAll(ep.id); }}
                          style={{ fontSize: 11, padding: '3px 10px', borderRadius: 4, border: `1px solid ${C.success}33`,
                            background: 'transparent', color: C.success, cursor: 'pointer' }}>
                          Approve All
                        </button>
                      )}
                      <button onClick={(e) => { e.stopPropagation(); setAddingClaimEpisode(ep.id); }}
                        style={{ fontSize: 11, padding: '3px 10px', borderRadius: 4, border: `1px solid ${C.accent}40`,
                          background: 'transparent', color: C.accent, cursor: 'pointer', marginLeft: 6 }}>
                        + Add Claim
                      </button>
                    </div>
                    {epClaims.map(claim => (
                      <ClaimRow key={claim.id} claim={claim} conversationId={conversationId}
                        isReviewed={reviewedClaims.has(claim.id)} isDismissed={dismissed[claim.id]}
                        isDeferred={deferred.has(claim.id)}
                        isEditing={editingClaim === claim.id} editText={editText}
                        showRelinkPrompt={relinkClaim === claim.id}
                        onApprove={handleApprove} onDefer={handleDefer} onDismiss={handleDismiss} onEdit={handleEdit}
                        onStartEdit={(c) => { setEditingClaim(c.id); setEditText(c.claim_text); }}
                        onCancelEdit={() => setEditingClaim(null)} onEditTextChange={setEditText}
                        onEntityLink={handleEntityLink} onRemoveEntity={handleRemoveEntity}
                        onDismissRelink={() => setRelinkClaim(null)}
                        contacts={contacts}
                        onBatchCorrect={handleBatchCorrect}
                        episodes={episodes} onReassign={handleReassign} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {addingClaimEpisode && (
        <AddClaimForm
          conversationId={conversationId}
          episodeId={addingClaimEpisode === '__orphan__' ? null : addingClaimEpisode}
          contacts={contacts}
          onCreated={handleAddClaim}
          onCancel={() => setAddingClaimEpisode(null)} />
      )}

      {orphanClaims.length > 0 && (
        <div style={{ ...cardStyle, marginTop: 8 }}>
          <h3 style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: 'uppercase', marginBottom: 8 }}>Unlinked Claims</h3>
          {orphanClaims.map(claim => (
            <ClaimRow key={claim.id} claim={claim} conversationId={conversationId}
              isReviewed={reviewedClaims.has(claim.id)} isDismissed={dismissed[claim.id]}
              isDeferred={deferred.has(claim.id)}
              isEditing={editingClaim === claim.id} editText={editText}
              showRelinkPrompt={relinkClaim === claim.id}
              onApprove={handleApprove} onDefer={handleDefer} onDismiss={handleDismiss} onEdit={handleEdit}
              onStartEdit={(c) => { setEditingClaim(c.id); setEditText(c.claim_text); }}
              onCancelEdit={() => setEditingClaim(null)} onEditTextChange={setEditText}
              onEntityLink={handleEntityLink} onRemoveEntity={handleRemoveEntity}
              onDismissRelink={() => setRelinkClaim(null)}
              contacts={contacts}
              onBatchCorrect={handleBatchCorrect}
              episodes={episodes} onReassign={handleReassign} />
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// CLAIM ROW — reusable in Episodes and Claims tabs
// ═══════════════════════════════════════════════════════


export function AddClaimForm({ conversationId, episodeId, contacts, onCreated, onCancel }) {
  const [claimType, setClaimType] = useState('fact');
  const [claimText, setClaimText] = useState('');
  const [subjectName, setSubjectName] = useState('');
  const [subjectEntityId, setSubjectEntityId] = useState(null);
  const [evidenceQuote, setEvidenceQuote] = useState('');
  const [firmness, setFirmness] = useState('');
  const [direction, setDirection] = useState('');
  const [saving, setSaving] = useState(false);
  const [contactSearch, setContactSearch] = useState('');

  const filteredContacts = contacts.filter(c =>
    c.display_name?.toLowerCase().includes(contactSearch.toLowerCase())
  ).slice(0, 8);

  const handleSubmit = async () => {
    if (!claimText.trim()) return;
    setSaving(true);
    try {
      const data = {
        conversation_id: conversationId,
        episode_id: episodeId || null,
        claim_type: claimType,
        claim_text: claimText.trim(),
        subject_name: subjectName || null,
        subject_entity_id: subjectEntityId || null,
        evidence_quote: evidenceQuote || null,
      };
      if (claimType === 'commitment') {
        data.firmness = firmness || null;
        data.direction = direction || null;
      }
      const result = await api.addClaim(data);
      if (result.claim) onCreated(result.claim);
      onCancel();
    } catch (e) { console.error('Add claim failed', e); }
    setSaving(false);
  };

  const S = {
    label: { fontSize: 11, color: C.textMuted, marginBottom: 2, display: 'block' },
    select: { fontSize: 12, padding: '4px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%' },
    input: { fontSize: 12, padding: '4px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%' },
    textarea: { fontSize: 12, padding: '4px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%', resize: 'vertical' },
  };

  return (
    <div style={{ padding: '12px', borderRadius: 6, background: C.accent + '08',
      border: `1px solid ${C.accent}40`, marginTop: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.accent, marginBottom: 10 }}>
        Add New Claim
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
        <div style={{ flex: '0 0 140px' }}>
          <label style={S.label}>Type</label>
          <select style={S.select} value={claimType} onChange={e => setClaimType(e.target.value)}>
            <option value="fact">fact</option>
            <option value="position">position</option>
            <option value="commitment">commitment</option>
            <option value="preference">preference</option>
            <option value="relationship">relationship</option>
            <option value="observation">observation</option>
            <option value="tactical">tactical</option>
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={S.label}>Subject</label>
          <div style={{ position: 'relative' }}>
            <input style={S.input} placeholder="Type to search contacts..."
              value={contactSearch || subjectName}
              onChange={e => {
                setContactSearch(e.target.value);
                setSubjectName(e.target.value);
                setSubjectEntityId(null);
              }} />
            {contactSearch && filteredContacts.length > 0 && !subjectEntityId && (
              <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10,
                background: C.cardBg || '#1a1f2e', border: `1px solid ${C.border}`,
                borderRadius: 4, maxHeight: 150, overflowY: 'auto' }}>
                {filteredContacts.map(c => (
                  <div key={c.id} onClick={() => {
                    setSubjectName(c.display_name);
                    setSubjectEntityId(c.id);
                    setContactSearch('');
                  }} style={{ padding: '4px 8px', cursor: 'pointer', fontSize: 12, color: C.text,
                    borderBottom: `1px solid ${C.border}` }}
                    onMouseEnter={e => e.target.style.background = C.accent + '20'}
                    onMouseLeave={e => e.target.style.background = 'transparent'}>
                    {c.display_name}
                  </div>
                ))}
              </div>
            )}
          </div>
          {subjectEntityId && <span style={{ fontSize: 10, color: C.success }}>✓ Linked</span>}
        </div>
      </div>
      <div style={{ marginBottom: 8 }}>
        <label style={S.label}>Claim Text *</label>
        <textarea style={{ ...S.textarea, height: 60 }} placeholder="What was said or implied..."
          value={claimText} onChange={e => setClaimText(e.target.value)} />
      </div>
      {claimType === 'commitment' && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={S.label}>Firmness</label>
            <select style={S.select} value={firmness} onChange={e => setFirmness(e.target.value)}>
              <option value="">unclassified</option>
              <option value="concrete">concrete</option>
              <option value="intentional">intentional</option>
              <option value="tentative">tentative</option>
              <option value="social">social</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label style={S.label}>Direction</label>
            <select style={S.select} value={direction} onChange={e => setDirection(e.target.value)}>
              <option value="">unknown</option>
              <option value="owed_by_me">owed_by_me</option>
              <option value="owed_to_me">owed_to_me</option>
              <option value="owed_by_other">owed_by_other</option>
              <option value="mutual">mutual</option>
            </select>
          </div>
        </div>
      )}
      <div style={{ marginBottom: 8 }}>
        <label style={S.label}>Evidence Quote (optional)</label>
        <input style={S.input} placeholder="Verbatim quote from transcript..."
          value={evidenceQuote} onChange={e => setEvidenceQuote(e.target.value)} />
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button onClick={onCancel}
          style={{ fontSize: 11, padding: '4px 12px', borderRadius: 3,
            border: `1px solid ${C.border}`, background: 'transparent',
            color: C.textDim, cursor: 'pointer' }}>Cancel</button>
        <button onClick={handleSubmit} disabled={saving || !claimText.trim()}
          style={{ fontSize: 11, padding: '4px 12px', borderRadius: 3, border: 'none',
            background: C.accent, color: '#fff', cursor: 'pointer',
            opacity: (saving || !claimText.trim()) ? 0.5 : 1 }}>
          {saving ? 'Creating...' : 'Create Claim'}
        </button>
      </div>
    </div>
  );
}


export function CommitmentEditPanel({ claim, conversationId, onSave, onCancel }) {
  const [fields, setFields] = useState({
    firmness: claim.firmness || '',
    direction: claim.direction || '',
    has_specific_action: !!claim.has_specific_action,
    has_deadline: !!claim.has_deadline,
    time_horizon: claim.time_horizon || '',
    has_condition: !!claim.has_condition,
    condition_text: claim.condition_text || '',
  });
  const [feedback, setFeedback] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await api.correctClaimBatch(conversationId, claim.id, fields, feedback || null);
      onSave(result.claim || { ...claim, ...fields, review_status: 'user_corrected' });
    } catch (e) {
      console.error('Batch save failed', e);
    }
    setSaving(false);
  };

  const S = { label: { fontSize: 11, color: C.textMuted, marginBottom: 2, display: 'block' },
    select: { fontSize: 12, padding: '3px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%' },
    input: { fontSize: 12, padding: '3px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%' },
    toggle: { display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12, color: C.text },
    row: { display: 'flex', gap: 12, flexWrap: 'wrap' },
    col: { flex: '1 1 140px', minWidth: 120 },
  };

  return (
    <div style={{ marginTop: 6, padding: '10px 12px', borderRadius: 6,
      background: C.warning + '08', border: `1px solid ${C.warning}40` }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.warning, marginBottom: 8 }}>
        Edit Commitment Fields
      </div>
      <div style={S.row}>
        <div style={S.col}>
          <label style={S.label}>Firmness</label>
          <select style={S.select} value={fields.firmness}
            onChange={e => setFields(p => ({ ...p, firmness: e.target.value }))}>
            <option value="">unclassified</option>
            <option value="concrete">concrete</option>
            <option value="intentional">intentional</option>
            <option value="tentative">tentative</option>
            <option value="social">social</option>
          </select>
        </div>
        <div style={S.col}>
          <label style={S.label}>Direction</label>
          <select style={S.select} value={fields.direction}
            onChange={e => setFields(p => ({ ...p, direction: e.target.value }))}>
            <option value="">unknown</option>
            <option value="owed_by_me">owed_by_me</option>
            <option value="owed_to_me">owed_to_me</option>
            <option value="owed_by_other">owed_by_other</option>
            <option value="mutual">mutual</option>
          </select>
        </div>
      </div>
      <div style={{ ...S.row, marginTop: 8 }}>
        <div style={S.col}>
          <label style={S.toggle}>
            <input type="checkbox" checked={fields.has_specific_action}
              onChange={e => setFields(p => ({ ...p, has_specific_action: e.target.checked }))} />
            Has specific action
          </label>
        </div>
        <div style={S.col}>
          <label style={S.toggle}>
            <input type="checkbox" checked={fields.has_deadline}
              onChange={e => setFields(p => ({ ...p, has_deadline: e.target.checked }))} />
            Has deadline
          </label>
        </div>
      </div>
      {fields.has_deadline && (
        <div style={{ marginTop: 6 }}>
          <label style={S.label}>Time Horizon</label>
          <input style={S.input} type="text" placeholder="e.g. 2026-03-15 or next week"
            value={fields.time_horizon}
            onChange={e => setFields(p => ({ ...p, time_horizon: e.target.value }))} />
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <label style={S.toggle}>
          <input type="checkbox" checked={fields.has_condition}
            onChange={e => setFields(p => ({ ...p, has_condition: e.target.checked }))} />
          Has condition
        </label>
      </div>
      {fields.has_condition && (
        <div style={{ marginTop: 4 }}>
          <label style={S.label}>Condition Text</label>
          <input style={S.input} type="text" placeholder="e.g. if budget is approved"
            value={fields.condition_text}
            onChange={e => setFields(p => ({ ...p, condition_text: e.target.value }))} />
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <label style={S.label}>Feedback (optional, for learning)</label>
        <textarea style={{ ...S.input, height: 40, resize: 'vertical' }}
          placeholder="Why are you making this change?"
          value={feedback} onChange={e => setFeedback(e.target.value)} />
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
        <button onClick={onCancel}
          style={{ fontSize: 11, padding: '4px 10px', borderRadius: 3,
            border: `1px solid ${C.border}`, background: 'transparent',
            color: C.textDim, cursor: 'pointer' }}>Cancel</button>
        <button onClick={handleSave} disabled={saving}
          style={{ fontSize: 11, padding: '4px 10px', borderRadius: 3, border: 'none',
            background: C.warning, color: '#fff', cursor: 'pointer',
            opacity: saving ? 0.6 : 1 }}>{saving ? 'Saving...' : 'Save'}</button>
      </div>
    </div>
  );
}

export function ClaimRow({ claim, conversationId, isReviewed, isDismissed, isDeferred, isEditing, editText,
  showRelinkPrompt, onApprove, onDefer, onDismiss, onEdit, onStartEdit, onCancelEdit, onEditTextChange,
  onEntityLink, onRemoveEntity, onDismissRelink, contacts, onBatchCorrect, episodes, onReassign }) {
  const [editingSubFieldsClaim, setEditingSubFieldsClaim] = useState(null);
  const [showReassign, setShowReassign] = useState(false);

  // Parse display_overrides for amber highlighting
  const overrides = claim.display_overrides ? (
    typeof claim.display_overrides === 'string' ? JSON.parse(claim.display_overrides) : claim.display_overrides
  ) : null;

  return (
    <div data-testid={`claim-row-${claim.id}`} style={{
      padding: '10px 0', borderBottom: `1px solid ${C.border}`,
      opacity: isDismissed ? 0.35 : isDeferred ? 0.5 : isReviewed ? 0.7 : 1,
      borderLeft: isDismissed ? `3px solid ${C.danger}33`
        : isDeferred ? `3px solid ${C.purple}33`
        : isReviewed ? `3px solid ${(claim.review_status === 'user_corrected' ? C.amber : C.success)}33`
        : '3px solid transparent',
      paddingLeft: 10,
    }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, fontWeight: 600,
          background: `${claimTypeColors[claim.claim_type] || C.textDim}22`,
          color: claimTypeColors[claim.claim_type] || C.textDim, textTransform: 'uppercase' }}>
          {claim.claim_type}
        </span>
        {claim.confidence != null && (
          <span style={{ fontSize: 11, color: C.textDim }}>{(claim.confidence * 100).toFixed(0)}%</span>
        )}
        <EntityChips claim={claim} contacts={contacts} onLink={onEntityLink}
          onRemoveEntity={onRemoveEntity} conversationId={conversationId} />

        {/* Review status badge */}
        {(claim.review_status === 'user_confirmed' || claim.review_status === 'user_corrected' || claim.review_status === 'dismissed' || claim.review_status === 'deferred') && (
          <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
            background: claim.review_status === 'dismissed' ? `${C.danger}22`
              : claim.review_status === 'deferred' ? `${C.purple}22`
              : claim.review_status === 'user_corrected' ? `${C.amber}22`
              : `${C.success}22`,
            color: claim.review_status === 'dismissed' ? C.danger
              : claim.review_status === 'deferred' ? C.purple
              : claim.review_status === 'user_corrected' ? C.amber
              : C.success }}>
            {claim.review_status === 'dismissed' ? 'dismissed'
              : claim.review_status === 'deferred' ? 'deferred'
              : claim.review_status === 'user_corrected' ? 'corrected'
              : 'confirmed'}
          </span>
        )}

        <div style={{ flex: 1 }} />
        {!isDismissed && !isReviewed && !isDeferred && (
          <div style={{ display: 'flex', gap: 4 }}>
            <button onClick={() => onApprove(claim.id)} data-testid={`claim-approve-${claim.id}`}
              style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, border: `1px solid ${C.success}44`,
                background: 'transparent', color: C.success, cursor: 'pointer' }}>{'✓'}</button>
            <button onClick={() => onDefer(claim.id)} data-testid={`claim-defer-${claim.id}`}
              style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, border: `1px solid ${C.purple}44`,
                background: 'transparent', color: C.purple, cursor: 'pointer' }}>Defer</button>
            <button onClick={() => onStartEdit(claim)} data-testid={`claim-edit-${claim.id}`}
              style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, border: `1px solid ${C.border}`,
                background: 'transparent', color: C.textDim, cursor: 'pointer' }}>Edit</button>
            {episodes && episodes.length > 1 && onReassign && (
              <div style={{ position: 'relative' }}>
                <button onClick={() => setShowReassign(!showReassign)}
                  style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, border: `1px solid ${C.border}`,
                    background: showReassign ? C.accent + '15' : 'transparent',
                    color: C.textDim, cursor: 'pointer' }}
                  title="Move to different episode">{'⇄'}</button>
                {showReassign && (
                  <div style={{ position: 'absolute', top: '100%', right: 0, zIndex: 20,
                    background: C.cardBg || '#1a1f2e', border: `1px solid ${C.border}`,
                    borderRadius: 4, minWidth: 200, maxHeight: 200, overflowY: 'auto',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.3)', marginTop: 2 }}>
                    <div style={{ padding: '4px 8px', fontSize: 10, color: C.textMuted,
                      borderBottom: `1px solid ${C.border}`, textTransform: 'uppercase' }}>
                      Move to episode
                    </div>
                    {episodes.map(ep => (
                      <div key={ep.id} onClick={() => {
                          if (ep.id !== claim.episode_id) {
                            onReassign(claim.id, ep.id);
                            setShowReassign(false);
                          }
                        }}
                        style={{ padding: '6px 10px', cursor: ep.id === claim.episode_id ? 'default' : 'pointer',
                          fontSize: 12, color: ep.id === claim.episode_id ? C.textMuted : C.text,
                          background: ep.id === claim.episode_id ? C.accent + '10' : 'transparent',
                          borderBottom: `1px solid ${C.border}20` }}
                        onMouseEnter={e => { if (ep.id !== claim.episode_id) e.target.style.background = C.accent + '15'; }}
                        onMouseLeave={e => { if (ep.id !== claim.episode_id) e.target.style.background = 'transparent'; }}>
                        {ep.id === claim.episode_id ? '✓ ' : ''}{ep.title || `Episode ${episodes.indexOf(ep) + 1}`}
                      </div>
                    ))}
                    <div onClick={() => {
                        if (claim.episode_id) {
                          onReassign(claim.id, null);
                          setShowReassign(false);
                        }
                      }}
                      style={{ padding: '6px 10px', cursor: !claim.episode_id ? 'default' : 'pointer',
                        fontSize: 12, color: !claim.episode_id ? C.textMuted : C.warning,
                        fontStyle: 'italic', borderTop: `1px solid ${C.border}` }}
                      onMouseEnter={e => { if (claim.episode_id) e.target.style.background = C.warning + '10'; }}
                      onMouseLeave={e => { if (claim.episode_id) e.target.style.background = 'transparent'; }}>
                      {!claim.episode_id ? '✓ ' : ''}Unlinked (orphan)
                    </div>
                  </div>
                )}
              </div>
            )}
            <span data-testid={`claim-dismiss-${claim.id}`}><ErrorTypeDropdown claim={claim} onSelect={onDismiss} /></span>
          </div>
        )}
        {isDismissed && <span style={{ fontSize: 11, color: C.danger, textDecoration: 'line-through' }}>{isDismissed.replace(/_/g, ' ')}</span>}
        {isDeferred && <span style={{ fontSize: 11, color: C.purple }}>deferred</span>}
        {isReviewed && !isDismissed && !isDeferred && (
          <span style={{ fontSize: 11, color: claim.review_status === 'user_corrected' ? C.amber : C.success }}>
            {claim.review_status === 'user_corrected' ? 'corrected' : 'confirmed'}
          </span>
        )}
      </div>

      {isEditing ? (
        <div style={{ marginTop: 6 }}>
          <textarea value={editText} onChange={e => onEditTextChange(e.target.value)}
            style={{ width: '100%', minHeight: 60, background: C.bg, border: `1px solid ${C.border}`,
              borderRadius: 4, padding: 8, fontSize: 13, color: C.text, resize: 'vertical', fontFamily: 'inherit' }} />
          <div style={{ display: 'flex', gap: 6, marginTop: 4, justifyContent: 'flex-end' }}>
            <button onClick={onCancelEdit}
              style={{ fontSize: 11, padding: '4px 10px', borderRadius: 3, border: `1px solid ${C.border}`,
                background: 'transparent', color: C.textDim, cursor: 'pointer' }}>Cancel</button>
            <button onClick={() => onEdit(claim)}
              style={{ fontSize: 11, padding: '4px 10px', borderRadius: 3, border: 'none',
                background: C.accent, color: '#fff', cursor: 'pointer' }}>Save</button>
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 13, color: C.text, lineHeight: 1.5 }}>
          <ClaimTextWithOverrides text={claim.claim_text} overrides={overrides} />
        </div>
      )}

      {claim.evidence_quote && !isEditing && (
        <div style={{ fontSize: 12, color: C.textDim, marginTop: 6,
          borderLeft: `2px solid ${C.border}`, paddingLeft: 10, fontStyle: 'italic' }}>
          &ldquo;{claim.evidence_quote}&rdquo;
        </div>
      )}

      {claim.claim_type === 'commitment' && (
        editingSubFieldsClaim === claim.id ? (
          <CommitmentEditPanel claim={claim} conversationId={conversationId}
            onSave={(updated) => {
              setEditingSubFieldsClaim(null);
              if (onBatchCorrect) onBatchCorrect(claim.id, updated);
            }}
            onCancel={() => setEditingSubFieldsClaim(null)} />
        ) : (
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 6, padding: '6px 8px',
            background: C.warning + '10', borderRadius: 4, border: '1px solid ' + C.warning + '30',
            position: 'relative' }}>
            <span style={{ fontSize: 11, color: C.warning }}>
              Firmness: <strong>{claim.firmness || 'unclassified'}</strong>
            </span>
            <span style={{ fontSize: 11, color: C.textMuted }}>
              Direction: {claim.direction || '—'}
            </span>
            {claim.has_specific_action && <span style={{ fontSize: 11, color: C.accent }}>[action]</span>}
            {claim.has_deadline && <span style={{ fontSize: 11, color: C.success }}>[deadline]</span>}
            {claim.has_condition && <span style={{ fontSize: 11, color: C.purple }}>Conditional{claim.condition_text ? ': ' + claim.condition_text : ''}</span>}
            {claim.time_horizon && claim.time_horizon !== 'none' && (
              <span style={{ fontSize: 11, color: C.textDim }}>Horizon: {claim.time_horizon}</span>
            )}
            <button onClick={() => setEditingSubFieldsClaim(claim.id)}
              style={{ position: 'absolute', right: 4, top: 4, background: 'none', border: 'none',
                cursor: 'pointer', fontSize: 11, color: C.textDim, padding: '2px 4px' }}
              title="Edit commitment fields">✎</button>
          </div>
        )
      )}
      {/* Entity-text mismatch indicator */}
      {claim.linked_entity_name && claim.claim_text && !claim.claim_text.toLowerCase().includes((claim.linked_entity_name || '').toLowerCase()) && (
        <div style={{ fontSize: 11, color: C.amber || '#f59e0b', marginTop: 4 }}>
          ⚠ Entity-text mismatch: linked to &ldquo;{claim.linked_entity_name}&rdquo; but name not in claim text
        </div>
      )}

      {/* Re-link prompt after text edit */}
      {showRelinkPrompt && (
        <div style={{
          marginTop: 8, padding: '10px 12px', borderRadius: 6,
          background: C.accent + '0a', border: `1px solid ${C.accent}33`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: C.accent, fontWeight: 500 }}>
              Entity links may need updating. Review linked entities?
            </span>
            <div style={{ flex: 1 }} />
            <button onClick={onDismissRelink}
              style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3,
                border: `1px solid ${C.border}`, background: 'transparent',
                color: C.textDim, cursor: 'pointer' }}>
              Dismiss
            </button>
          </div>
          <EntityChips claim={claim} contacts={contacts}
            onLink={(c, contactId) => { onEntityLink(c, contactId); onDismissRelink(); }}
            onRemoveEntity={onRemoveEntity}
            conversationId={conversationId} />
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// CLAIM TEXT WITH DISPLAY OVERRIDES — amber highlighting
// ═══════════════════════════════════════════════════════
export function ClaimTextWithOverrides({ text, overrides }) {
  if (!overrides || !Array.isArray(overrides) || overrides.length === 0) {
    return <span>{text}</span>;
  }

  // Sort overrides by start position
  const sorted = [...overrides].sort((a, b) => a.start - b.start);
  const parts = [];
  let lastEnd = 0;

  for (const ov of sorted) {
    // Text before this override
    if (ov.start > lastEnd) {
      parts.push(<span key={`t${lastEnd}`}>{text.slice(lastEnd, ov.start)}</span>);
    }
    // The overridden span with amber highlight
    parts.push(
      <span key={`o${ov.start}`} title={`Resolved: ${ov.resolved_name}`}
        style={{ background: `${C.amber}33`, color: C.amber, borderRadius: 2, padding: '0 2px' }}>
        {text.slice(ov.start, ov.end)}
        <span style={{ fontSize: 10, fontWeight: 600, marginLeft: 2 }}>{ov.resolved_name.split(' ').slice(1).join(' ')}</span>
      </span>
    );
    lastEnd = ov.end;
  }

  // Remaining text after last override
  if (lastEnd < text.length) {
    parts.push(<span key={`t${lastEnd}`}>{text.slice(lastEnd)}</span>);
  }

  return <span>{parts}</span>;
}

// ═══════════════════════════════════════════════════════
// ENTITY CHIPS — renders from claim_entities junction table
// ═══════════════════════════════════════════════════════
export function EntityChips({ claim, contacts, onLink, onRemoveEntity, conversationId }) {
  const entities = claim.entities || [];
  const [showAdd, setShowAdd] = useState(false);
  const [search, setSearch] = useState('');
  const [results, setResults] = useState([]);

  const handleSearch = async (q) => {
    setSearch(q);
    if (q.length < 2) { setResults([]); return; }
    try {
      const r = await api.searchContacts(q, 10);
      setResults(r.filter(c => c.is_confirmed !== 0));
    } catch { setResults(contacts.filter(c => c.is_confirmed !== 0 && c.canonical_name.toLowerCase().includes(q.toLowerCase())).slice(0, 10)); }
  };

  // Fallback: if no entities from junction table, show subject_name with link button
  const hasEntities = entities.length > 0;
  const subjectName = claim.linked_entity_name || claim.subject_name;

  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', position: 'relative' }}>
      {hasEntities ? (
        <>
          {entities.map(ent => (
            <span key={ent.id} style={{
              fontSize: 11, padding: '1px 6px', borderRadius: 3, display: 'inline-flex',
              alignItems: 'center', gap: 3,
              border: `1px solid ${C.success}44`, color: C.success,
            }}>
              {'\u{1F517}'} {ent.entity_name}
              {ent.role !== 'subject' && (
                <span style={{ fontSize: 9, color: C.textDim, marginLeft: 2 }}>({ent.role})</span>
              )}
              {ent.link_source === 'user' && (
                <span style={{ fontSize: 9, color: C.accent }} title="User-linked">*</span>
              )}
              {onRemoveEntity && (
                <button onClick={(e) => { e.stopPropagation(); onRemoveEntity(claim, ent.id); }}
                  style={{ fontSize: 9, color: C.textDim, cursor: 'pointer', background: 'none',
                    border: 'none', padding: '0 2px', lineHeight: 1 }}
                  title="Remove entity link">&times;</button>
              )}
            </span>
          ))}
        </>
      ) : subjectName ? (
        <button onClick={() => setShowAdd(!showAdd)}
          style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3,
            border: `1px solid ${C.warning}44`, background: 'transparent',
            color: C.warning, cursor: 'pointer' }}>
          {'\u{1F50D}'} {subjectName}
        </button>
      ) : null}

      {/* Add entity button */}
      <button onClick={() => setShowAdd(!showAdd)}
        style={{ fontSize: 11, padding: '1px 5px', borderRadius: 3,
          border: `1px solid ${C.border}`, background: 'transparent',
          color: C.textDim, cursor: 'pointer', lineHeight: 1 }}
        title="Add entity link">+</button>

      {/* Search dropdown */}
      {showAdd && (
        <div style={{ position: 'absolute', left: 0, top: '100%', marginTop: 4, zIndex: 50,
          background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, padding: 8,
          minWidth: 260, boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
          <input value={search} onChange={e => handleSearch(e.target.value)} placeholder="Search contacts..."
            autoFocus style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: C.bg,
              border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, marginBottom: 6, outline: 'none' }} />
          <div style={{ maxHeight: 200, overflow: 'auto' }}>
            {results.map(c => (
              <button key={c.id} onClick={() => { onLink(claim, c.id); setShowAdd(false); setSearch(''); setResults([]); }}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 8px',
                  fontSize: 12, color: C.text, background: 'transparent', border: 'none', cursor: 'pointer', borderRadius: 4 }}
                onMouseEnter={e => e.target.style.background = C.cardHover}
                onMouseLeave={e => e.target.style.background = 'transparent'}>
                {c.canonical_name}
                {c.email && <span style={{ color: C.textDim, marginLeft: 6 }}>{c.email}</span>}
              </button>
            ))}
            {search.length >= 2 && results.length === 0 && (
              <p style={{ fontSize: 12, color: C.textDim, padding: 6 }}>No matches</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Legacy wrapper for backward compatibility
function EntityLinkButton({ claim, contacts, onLink }) {
  return <EntityChips claim={claim} contacts={contacts} onLink={onLink} />;
}

// ═══════════════════════════════════════════════════════
// ERROR TYPE DROPDOWN
// ═══════════════════════════════════════════════════════
export function ErrorTypeDropdown({ claim, onSelect }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => setOpen(!open)}
        style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, border: `1px solid ${C.border}`,
          background: 'transparent', color: C.danger, cursor: 'pointer' }}>Flag</button>
      {open && (
        <div style={{ position: 'absolute', right: 0, top: '100%', marginTop: 4, zIndex: 50,
          background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, padding: 4,
          minWidth: 240, boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
          {errorTypes.map(et => (
            <button key={et.value} onClick={() => { onSelect(claim, et.value); setOpen(false); }}
              style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 10px',
                fontSize: 12, color: C.textMuted, background: 'transparent', border: 'none', cursor: 'pointer', borderRadius: 4 }}
              onMouseEnter={e => e.target.style.background = C.cardHover}
              onMouseLeave={e => e.target.style.background = 'transparent'}>
              {et.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// TRANSCRIPT TAB — Speaker correction + text editing
// ═══════════════════════════════════════════════════════
export function TranscriptTab({ transcript, conversationId, contacts }) {
  const [editingSeg, setEditingSeg] = useState(null);
  const [editText, setEditText] = useState('');
  const [correctedSegs, setCorrectedSegs] = useState(new Set());
  const [speakerDropdown, setSpeakerDropdown] = useState(null);
  const [speakerSearch, setSpeakerSearch] = useState('');
  const [localTranscript, setLocalTranscript] = useState(transcript);

  useEffect(() => setLocalTranscript(transcript), [transcript]);

  const handleSaveText = async (seg) => {
    try {
      await api.editTranscript(seg.id, editText);
      setCorrectedSegs(prev => new Set(prev).add(seg.id));
      setLocalTranscript(prev => prev.map(s => s.id === seg.id ? { ...s, text: editText, user_corrected: 1 } : s));
      setEditingSeg(null);
    } catch (e) { console.error('Edit failed', e); }
  };

  const handleSpeakerChange = async (seg, contactId) => {
    try {
      await api.correctSpeaker(conversationId, seg.speaker_label, contactId);
      const contact = contacts.find(c => c.id === contactId);
      setLocalTranscript(prev => prev.map(s =>
        s.speaker_label === seg.speaker_label ? { ...s, speaker_id: contactId, speaker_name: contact?.canonical_name || contactId } : s
      ));
      setSpeakerDropdown(null);
    } catch (e) { console.error('Speaker correction failed', e); }
  };

  const filteredContacts = speakerSearch
    ? contacts.filter(c => c.canonical_name.toLowerCase().includes(speakerSearch.toLowerCase())).slice(0, 10)
    : contacts.slice(0, 10);

  return (
    <div style={cardStyle}>
      {localTranscript.length === 0 ? (
        <p style={{ color: C.textDim, fontSize: 13, textAlign: 'center', padding: 30 }}>No transcript available.</p>
      ) : (
        <div>
          {localTranscript.map((seg, i) => (
            <div key={seg.id || i} style={{
              padding: '8px 0', borderBottom: i < localTranscript.length - 1 ? `1px solid ${C.border}` : 'none',
              display: 'flex', gap: 8, alignItems: 'flex-start',
            }}>
              <div style={{ position: 'relative', flexShrink: 0, minWidth: 100 }}>
                <button onClick={() => { setSpeakerDropdown(speakerDropdown === seg.id ? null : seg.id); setSpeakerSearch(''); }}
                  style={{ fontSize: 12, fontWeight: 600, background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px', borderRadius: 3,
                    color: seg.speaker_label === 'SPEAKER_00' ? C.accent : C.purple }}>
                  {seg.speaker_name || seg.speaker_label || 'Unknown'}
                </button>
                {seg.speaker_id && (
                  <span style={{ fontSize: 9, color: seg.voice_sample_count ? C.success : C.textDim, marginLeft: 2 }}
                    title={seg.voice_sample_count ? `Voice enrolled (${seg.voice_sample_count} samples)` : 'Identified (no voiceprint)'}>
                    {seg.voice_sample_count ? '🎤' : ''}
                  </span>
                )}
                {!seg.speaker_id && (
                  <span style={{ fontSize: 9, color: C.warning, marginLeft: 2 }} title="Unknown speaker — assign to enroll">?</span>
                )}
                {speakerDropdown === seg.id && (
                  <div style={{ position: 'absolute', left: 0, top: '100%', marginTop: 4, zIndex: 50,
                    background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, padding: 8,
                    minWidth: 220, boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
                    <input value={speakerSearch} onChange={e => setSpeakerSearch(e.target.value)}
                      placeholder="Search..." autoFocus
                      style={{ width: '100%', padding: '4px 6px', fontSize: 12, background: C.bg,
                        border: `1px solid ${C.border}`, borderRadius: 3, color: C.text, marginBottom: 4, outline: 'none' }} />
                    {filteredContacts.map(c => (
                      <button key={c.id} onClick={() => handleSpeakerChange(seg, c.id)}
                        style={{ display: 'block', width: '100%', textAlign: 'left', padding: '5px 6px',
                          fontSize: 12, color: C.text, background: 'transparent', border: 'none', cursor: 'pointer', borderRadius: 3 }}
                        onMouseEnter={e => e.target.style.background = C.cardHover}
                        onMouseLeave={e => e.target.style.background = 'transparent'}>
                        {c.canonical_name}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <span style={{ fontSize: 11, color: C.textDim, flexShrink: 0, minWidth: 40 }}>
                {seg.start_time ? `${Number(seg.start_time).toFixed(1)}s` : ''}
              </span>

              <div style={{ flex: 1 }}>
                {editingSeg === seg.id ? (
                  <div>
                    <textarea value={editText} onChange={e => setEditText(e.target.value)}
                      style={{ width: '100%', minHeight: 40, background: C.bg, border: `1px solid ${C.accent}`,
                        borderRadius: 4, padding: 6, fontSize: 13, color: C.text, resize: 'vertical', fontFamily: 'inherit' }} />
                    <div style={{ display: 'flex', gap: 4, marginTop: 4, justifyContent: 'flex-end' }}>
                      <button onClick={() => setEditingSeg(null)}
                        style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3, border: `1px solid ${C.border}`,
                          background: 'transparent', color: C.textDim, cursor: 'pointer' }}>Cancel</button>
                      <button onClick={() => handleSaveText(seg)}
                        style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3, border: 'none',
                          background: C.accent, color: '#fff', cursor: 'pointer' }}>Save</button>
                    </div>
                  </div>
                ) : (
                  <span onClick={() => { setEditingSeg(seg.id); setEditText(seg.text); }}
                    style={{ fontSize: 13, color: C.text, cursor: 'pointer', display: 'inline' }}
                    title="Click to edit">
                    {seg.text}
                    {(seg.user_corrected || correctedSegs.has(seg.id)) && (
                      <span style={{ fontSize: 10, color: C.warning, marginLeft: 4 }} title="User corrected">{'\u270E'}</span>
                    )}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// CLAIMS TAB — Flat list
// ═══════════════════════════════════════════════════════
export function ClaimsTab({ claims: initialClaims, conversationId, contacts, updateClaim }) {
    const claims = initialClaims;
  const [dismissed, setDismissed] = useState(() => {
    const d = {};
    (initialClaims || []).forEach(c => {
      if (c.review_status === 'dismissed') d[c.id] = 'hallucinated_claim';
    });
    return d;
  });
  const [editingClaim, setEditingClaim] = useState(null);
  const [editText, setEditText] = useState('');
  const [relinkClaim, setRelinkClaim] = useState(null);
  const [relationshipPrompt, setRelationshipPrompt] = useState(null);
  const [reviewedClaims, setReviewedClaims] = useState(() => {
    const set = new Set();
    (initialClaims || []).forEach(c => {
      if (c.review_status === 'user_confirmed' || c.review_status === 'user_corrected') set.add(c.id);
    });
    return set;
  });
  const [deferred, setDeferred] = useState(() => {
    const d = new Set();
    (initialClaims || []).forEach(c => {
      if (c.review_status === 'deferred') d.add(c.id);
    });
    return d;
  });

    const handleBatchCorrect = (claimId, updatedClaim) => {
    updateClaim(claimId, { ...updatedClaim, review_status: 'user_corrected' });
  };

  const handleDismiss = async (claim, errorType) => {
    try {
      await api.dismissClaim(conversationId, claim.id, errorType, null);
      setDismissed(prev => ({ ...prev, [claim.id]: errorType }));
      updateClaim(claim.id, { review_status: 'dismissed' });
    } catch (e) { console.error('Flag failed', e); }
  };

  const handleDefer = async (claimId) => {
    // Optimistic update
    updateClaim(claimId, { review_status: 'deferred' });
    setDeferred(prev => new Set(prev).add(claimId));
    try {
      await api.deferClaim(conversationId, claimId);
    } catch (e) {
      console.error('Defer failed', e);
      updateClaim(claimId, { review_status: 'unreviewed' });  // rollback
      setDeferred(prev => { const s = new Set(prev); s.delete(claimId); return s; });
    }
  };

  const handleEdit = async (claim) => {
    try {
      await api.correctClaim(conversationId, claim.id, 'claim_text_edited', claim.claim_text, editText, null);
      claim.claim_text = editText;
      setEditingClaim(null);
      setRelinkClaim(claim.id);
    } catch (e) { console.error('Edit failed', e); }
  };

  const handleEntityLink = async (claim, contactId) => {
    try {
      const result = await api.linkEntity(conversationId, claim.id, contactId, claim.subject_name, null);
      const contact = contacts.find(c => c.id === contactId);
      const newName = contact ? contact.canonical_name : claim.subject_name;
      // Use entities from backend response (source of truth), matching EpisodesTab pattern
      if (result && result.entities) {
        updateClaim(claim.id, {
          subject_entity_id: contactId,
          subject_name: newName,
          entities: result.entities,
        });
      } else {
        // Fallback: update without entities
        updateClaim(claim.id, {
          subject_entity_id: contactId,
          subject_name: newName,
        });
      }
      if (result && result.text_updated && result.updated_text) {
        claim.claim_text = result.updated_text;
        claim.display_overrides = null;
      }
      if (result && result.relational_ref) {
        const ref = result.relational_ref;
        const linkedName = contact ? contact.canonical_name : '';
        const anchorContact = contacts.find(c => c.canonical_name === ref.anchor_name);
        if (anchorContact) {
          setRelationshipPrompt({
            anchorId: anchorContact.id,
            anchorName: ref.anchor_name,
            relationship: ref.relationship,
            targetId: contactId,
            targetName: linkedName,
            phrase: ref.phrase,
          });
        }
      }
    } catch (e) { console.error('Entity link failed', e); }
  };

  const handleRemoveEntity = async (claim, entityLinkId) => {
    try {
      await api.removeEntityLink(entityLinkId);
      if (claim.entities) {
        claim.entities = claim.entities.filter(e => e.id !== entityLinkId);
      }
      const subjectEntities = (claim.entities || []).filter(e => e.role === 'subject');
      const updates = { entities: [...(claim.entities || [])] };
      if (subjectEntities.length === 0) {
        updates.subject_entity_id = null;
        updates.subject_name = '';
      }
      updateClaim(claim.id, updates);
    } catch (e) { console.error('Remove entity link failed', e); }
  };

  const handleSaveRelationship = async () => {
    if (!relationshipPrompt) return;
    try {
      await api.saveRelationship(
        relationshipPrompt.anchorId,
        relationshipPrompt.relationship,
        relationshipPrompt.targetId,
        relationshipPrompt.targetName,
        relationshipPrompt.notes || undefined
      );
      setRelationshipPrompt(null);
    } catch (e) { console.error('Save relationship failed', e); }
  };

  return (
    <div style={cardStyle}>
      {relationshipPrompt && (
        <div style={{
          padding: '12px 16px', marginBottom: 12, borderRadius: 6,
          background: '#ec4899' + '15', border: '1px solid ' + '#ec4899' + '44',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div>
            <span style={{ fontSize: 13, color: C.text }}>
              Save this relationship? </span>
            <strong style={{ color: '#ec4899' }}>
              {relationshipPrompt.anchorName} → {relationshipPrompt.relationship} → {relationshipPrompt.targetName}
            </strong>
            <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
              Detected from: "{relationshipPrompt.phrase}"
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={handleSaveRelationship} style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
            }}>Save</button>
            <button onClick={() => setRelationshipPrompt(null)} style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: C.card, color: C.textDim, border: '1px solid ' + C.border,
            }}>Skip</button>
          </div>
        </div>
      )}
      {claims.length === 0 ? (
        <p style={{ color: C.textDim, fontSize: 13, textAlign: 'center', padding: 30 }}>No claims extracted.</p>
      ) : (
        <div>
          {claims.map(claim => (
            <ClaimRow key={claim.id} claim={claim} conversationId={conversationId}
              isReviewed={reviewedClaims.has(claim.id)} isDismissed={dismissed[claim.id]}
              isDeferred={deferred.has(claim.id)}
              isEditing={editingClaim === claim.id} editText={editText}
              showRelinkPrompt={relinkClaim === claim.id}
              onApprove={async (id) => {
                try {
                  await api.approveClaim(conversationId, id);
                  setReviewedClaims(prev => new Set(prev).add(id));
                  updateClaim(id, { review_status: 'user_confirmed' });
                } catch (e) { console.error('Approve failed', e); setReviewedClaims(prev => new Set(prev).add(id)); }
              }}
              onDefer={handleDefer} onDismiss={handleDismiss} onEdit={handleEdit}
              onStartEdit={(c) => { setEditingClaim(c.id); setEditText(c.claim_text); }}
              onCancelEdit={() => setEditingClaim(null)} onEditTextChange={setEditText}
              onEntityLink={handleEntityLink} onRemoveEntity={handleRemoveEntity}
              onDismissRelink={() => setRelinkClaim(null)}
              contacts={contacts}
              onBatchCorrect={handleBatchCorrect} />
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// SUMMARY TAB
// ═══════════════════════════════════════════════════════
export function SummaryTab({ synthesis, beliefUpdates, claims = [] }) {
  return (
    <div>
      {synthesis.summary && (
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Summary</h3>
          <p style={{ fontSize: 13, color: C.text, lineHeight: 1.6 }}>{synthesis.summary}</p>
        </div>
      )}
      {synthesis.vocal_intelligence_summary && (
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Vocal Intelligence</h3>
          <p style={{ fontSize: 13, color: C.text, lineHeight: 1.6 }}>{synthesis.vocal_intelligence_summary}</p>
        </div>
      )}
      {synthesis.topics_discussed?.length > 0 && (
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Topics</h3>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {synthesis.topics_discussed.map((t, i) => (
              <span key={i} style={{ fontSize: 12, padding: '4px 10px', borderRadius: 12,
                background: `${C.accent}15`, color: C.accent }}>{t}</span>
            ))}
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 16 }}>
        {(() => {
          const commitmentClaims = claims.filter(c => c.claim_type === 'commitment');
          const activeClaims = commitmentClaims.filter(c => c.review_status !== 'dismissed');
          const dismissedClaims = commitmentClaims.filter(c => c.review_status === 'dismissed');
          const iOwe = activeClaims.filter(c => c.direction === 'owed_by_me');
          const theyOwe = activeClaims.filter(c => c.direction === 'owed_to_me' || c.direction === 'owed_by_other');
          const otherActive = activeClaims.filter(c => !c.direction || (c.direction !== 'owed_by_me' && c.direction !== 'owed_to_me' && c.direction !== 'owed_by_other'));
          if (commitmentClaims.length === 0 && !synthesis.my_commitments?.length && !synthesis.contact_commitments?.length) return null;
          return (
            <div style={{ ...cardStyle, flex: 1 }}>
              <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Commitments</h3>
              {iOwe.map(c => <CommitmentRow key={c.id} claim={c} direction="I owe" />)}
              {theyOwe.map(c => <CommitmentRow key={c.id} claim={c} direction="They owe" />)}
              {otherActive.map(c => <CommitmentRow key={c.id} claim={c} direction="Commitment" />)}
              {dismissedClaims.length > 0 && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ fontSize: 11, color: C.textDim, cursor: 'pointer' }}>Dismissed ({dismissedClaims.length})</summary>
                  {dismissedClaims.map(c => <CommitmentRow key={c.id} claim={c} direction="Dismissed" isDismissed />)}
                </details>
              )}
            </div>
          );
        })()}
        {synthesis.follow_ups?.length > 0 && (
          <div style={{ ...cardStyle, flex: 1 }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Follow-ups</h3>
            {synthesis.follow_ups.map((f, i) => (
              <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}`, fontSize: 13 }}>
                <div style={{ color: C.text }}>{f.description}</div>
                {f.due_date && <div style={{ fontSize: 11, color: C.warning, marginTop: 2 }}>Due: {f.due_date}</div>}
              </div>
            ))}
          </div>
        )}
      </div>
      {beliefUpdates.length > 0 && (
        <div style={{ ...cardStyle, marginTop: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Belief Updates ({beliefUpdates.length})</h3>
          {beliefUpdates.map((b, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 11, padding: '2px 6px', borderRadius: 3,
                  background: `${C.success}22`, color: C.success }}>{b.status}</span>
                <span style={{ fontSize: 13, color: C.text }}>{b.belief_summary}</span>
              </div>
              {b.entity_name && (
                <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
                  {b.entity_name} &middot; {(b.confidence * 100).toFixed(0)}% confidence
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {synthesis.self_coaching?.length > 0 && (
        <div style={{ ...cardStyle, marginTop: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Self Coaching</h3>
          {synthesis.self_coaching.map((sc, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}`, fontSize: 13 }}>
              <div style={{ color: C.text }}>{sc.observation}</div>
              {sc.recommendation && <div style={{ fontSize: 12, color: C.accent, marginTop: 4 }}>&rarr; {sc.recommendation}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CommitmentRow({ claim, direction, isDismissed }) {
  const dirColor = direction === 'I owe' ? C.warning : direction === 'Dismissed' ? C.textDim : C.accent;
  const dirBg = direction === 'I owe' ? C.warning + '22' : direction === 'Dismissed' ? C.textDim + '15' : C.accent + '22';
  return (
    <div style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}`,
      opacity: isDismissed ? 0.4 : 1, textDecoration: isDismissed ? 'line-through' : 'none' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, fontWeight: 600,
          background: dirBg, color: dirColor, flexShrink: 0, marginTop: 2 }}>{direction}</span>
        <div style={{ flex: 1 }}>
          <span style={{ fontSize: 13, color: C.text }}>{claim.claim_text}</span>
          {(claim.firmness || claim.has_deadline || claim.has_condition || claim.has_specific_action) && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
              {claim.firmness && (
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                  background: C.warning + '15', color: C.warning }}>{claim.firmness}</span>
              )}
              {claim.has_specific_action && (
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                  background: C.accent + '15', color: C.accent }}>action</span>
              )}
              {claim.has_deadline && (
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                  background: C.success + '15', color: C.success }}>
                  deadline{claim.time_horizon && claim.time_horizon !== 'none' ? ': ' + claim.time_horizon : ''}
                </span>
              )}
              {claim.has_condition && (
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                  background: '#8b5cf6' + '15', color: '#8b5cf6' }}>
                  conditional{claim.condition_text ? ': ' + claim.condition_text : ''}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function RawTab({ extraction }) {
  return (
    <div style={cardStyle}>
      <pre style={{ fontSize: 12, color: C.textMuted, whiteSpace: 'pre-wrap', lineHeight: 1.6, maxHeight: 600, overflow: 'auto' }}>
        {extraction ? JSON.stringify(extraction, null, 2) : 'No extraction data available.'}
      </pre>
    </div>
  );
}


export function RelationalReferencesBanner({
  conversationId, contacts, onResolved,
  initialClaims,
  loadRelationalClaimsFn = api.unresolvedRelational,
  searchContactsFn = api.searchContacts,
  linkEntityFn = api.linkEntity,
  saveRelationshipFn = api.saveRelationship,
}) {
  const [claims, setClaims] = useState(initialClaims || []);
  const [loading, setLoading] = useState(!initialClaims);
  const [linkingId, setLinkingId] = useState(null);
  const [linkSearch, setLinkSearch] = useState('');
  const [linkResults, setLinkResults] = useState([]);
  const [linkedPeople, setLinkedPeople] = useState({});  // claimId -> [{name, id}]
  const [relPrompt, setRelPrompt] = useState(null);
  const [editingAnchorId, setEditingAnchorId] = useState(null);
  const [anchorSearch, setAnchorSearch] = useState('');
  const [anchorResults, setAnchorResults] = useState([]);

  useEffect(() => {
    if (initialClaims) return;
    loadRelationalClaimsFn(conversationId, 30)
      .then(d => setClaims(d.relational_claims || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conversationId, initialClaims, loadRelationalClaimsFn]);

  const handleSearch = async (q) => {
    setLinkSearch(q);
    if (q.length < 2) { setLinkResults([]); return; }
    try {
      const results = await searchContactsFn(q, 10);
      setLinkResults(results.filter(c => c.is_confirmed !== 0));
    } catch { setLinkResults([]); }
  };

  const handleLink = async (claim, contactId) => {
    try {
      const contact = contacts.find(c => c.id === contactId) || linkResults.find(c => c.id === contactId);
      const contactName = contact ? contact.canonical_name : '';
      const result = await linkEntityFn(conversationId, claim.id, contactId, claim.subject_name, null);

      // Track linked people for this claim
      setLinkedPeople(prev => ({
        ...prev,
        [claim.id]: [...(prev[claim.id] || []), { id: contactId, name: contactName }],
      }));

      // If relational reference detected, prompt to save relationship
      if (result && result.relational_ref) {
        const ref = result.relational_ref;
        const anchorContact = contacts.find(c => c.canonical_name === ref.anchor_name);
        if (anchorContact) {
          setRelPrompt({
            claimId: claim.id,
            anchorId: anchorContact.id,
            anchorName: ref.anchor_name,
            relationship: ref.relationship,
            isPlural: ref.is_plural,
            targetId: contactId,
            targetName: contactName,
            phrase: ref.phrase,
          });
        }
      }

      // Reset search but keep linking open for plurals
      setLinkSearch('');
      setLinkResults([]);
      if (!claim.is_plural) {
        setLinkingId(null);
      }
    } catch (e) { console.error('Link failed', e); }
  };

  const handleSaveRel = async () => {
    if (!relPrompt) return;
    try {
      const targets = relPrompt.targets || [{ id: relPrompt.targetId, name: relPrompt.targetName }];
      // Save one relationship per target (multi-target support, Bug 10)
      for (const target of targets) {
        await saveRelationshipFn(
          relPrompt.anchorId, relPrompt.relationship.trim(),
          target.id, target.name
        );
      }
      setRelPrompt(null);
      if (onResolved) onResolved();
    } catch (e) { console.error('Save relationship failed', e); }
  };

  const unresolved = claims.filter(c => !c.subject_entity_id || c.is_plural);
  if (loading || unresolved.length === 0) return null;

  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: '#ec4899' + '66',
      background: '#ec4899' + '0a',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 16 }}>🔗</span>
        <span style={{ color: '#ec4899', fontWeight: 600, fontSize: 14 }}>
          Relational References ({unresolved.length})
        </span>
        <span style={{ color: C.textDim, fontSize: 12 }}>
          — People mentioned by relationship that need linking to contacts
        </span>
      </div>

      {/* Relationship detail form (Bug 10) */}
      {relPrompt && (
        <div style={{
          padding: '14px 16px', marginBottom: 10, borderRadius: 6,
          background: C.success + '08', border: '1px solid ' + C.success + '33',
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.success, marginBottom: 10 }}>
            Save Relationship
          </div>

          {/* Relationship type — editable */}
          <div style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Relationship Type</label>
            <input
              value={relPrompt.relationship}
              onChange={e => setRelPrompt(p => ({ ...p, relationship: e.target.value }))}
              style={{ width: '100%', padding: '5px 8px', fontSize: 13, borderRadius: 4,
                background: C.bg, color: C.text, border: '1px solid ' + C.border, outline: 'none', boxSizing: 'border-box' }}
              placeholder="e.g., son, birth mother, colleague" />
          </div>

          {/* Source person (anchor) */}
          <div style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Source Person (who has this relationship)</label>
            <div style={{ fontSize: 13, color: '#ec4899', fontWeight: 500, padding: '5px 8px',
              background: C.card, borderRadius: 4, border: '1px solid ' + C.border }}>
              {relPrompt.anchorName}
            </div>
          </div>

          {/* Target person(s) — with "add another" */}
          <div style={{ marginBottom: 10 }}>
            <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Related To (target person)</label>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
              {(relPrompt.targets || [{ id: relPrompt.targetId, name: relPrompt.targetName }]).map((t, i) => (
                <span key={i} style={{
                  fontSize: 12, padding: '3px 8px', borderRadius: 4,
                  background: '#ec4899' + '22', color: '#ec4899', display: 'inline-flex', alignItems: 'center', gap: 4,
                }}>
                  {t.name}
                  {(relPrompt.targets || []).length > 1 && (
                    <button onClick={() => setRelPrompt(p => ({
                      ...p,
                      targets: (p.targets || []).filter((_, j) => j !== i),
                    }))} style={{ fontSize: 10, background: 'none', border: 'none', color: C.textDim, cursor: 'pointer', padding: 0 }}>&times;</button>
                  )}
                </span>
              ))}
            </div>
            {/* Add another target button + search */}
            {relPrompt.addingTarget ? (
              <div>
                <input
                  value={relPrompt.targetSearch || ''}
                  onChange={async (e) => {
                    const q = e.target.value;
                    setRelPrompt(p => ({ ...p, targetSearch: q }));
                    if (q.length >= 2) {
                      try {
                        const results = await searchContactsFn(q, 8);
                        setRelPrompt(p => ({ ...p, targetResults: results }));
                      } catch {}
                    }
                  }}
                  placeholder="Search contacts..."
                  autoFocus
                  style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4,
                    background: C.bg, color: C.text, border: '1px solid ' + C.border, outline: 'none', boxSizing: 'border-box' }}
                />
                {(relPrompt.targetResults || []).map(r => (
                  <div key={r.id}
                    onClick={() => {
                      const targets = relPrompt.targets || [{ id: relPrompt.targetId, name: relPrompt.targetName }];
                      if (!targets.find(t => t.id === r.id)) {
                        setRelPrompt(p => ({
                          ...p,
                          targets: [...targets, { id: r.id, name: r.canonical_name }],
                          addingTarget: false, targetSearch: '', targetResults: [],
                        }));
                      }
                    }}
                    style={{ padding: '5px 8px', fontSize: 12, color: C.text, cursor: 'pointer', borderRadius: 3 }}
                    onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                    {r.canonical_name}
                  </div>
                ))}
                <button onClick={() => setRelPrompt(p => ({ ...p, addingTarget: false }))}
                  style={{ fontSize: 11, color: C.textDim, background: 'none', border: 'none', cursor: 'pointer', marginTop: 4 }}>
                  Cancel
                </button>
              </div>
            ) : (
              <button onClick={() => setRelPrompt(p => ({ ...p, addingTarget: true }))}
                style={{ fontSize: 11, padding: '3px 8px', borderRadius: 4, cursor: 'pointer',
                  background: 'transparent', color: C.accent, border: '1px solid ' + C.accent + '44' }}>
                + Add another person
              </button>
            )}
          </div>

          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
            <button onClick={handleSaveRel} style={{
              padding: '6px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44', fontWeight: 500,
            }}>Save Relationship</button>
            <button onClick={() => setRelPrompt(null)} style={{
              padding: '6px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: C.card, color: C.textDim, border: '1px solid ' + C.border,
            }}>Skip</button>
          </div>
        </div>
      )}

      {unresolved.map(c => {
        const linked = linkedPeople[c.id] || [];
        return (
          <div key={c.id} style={{
            padding: '10px 12px', marginBottom: 8,
            background: C.card, borderRadius: 6, border: '1px solid ' + C.border,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <span style={{ color: '#ec4899', fontSize: 12, fontWeight: 600 }}>
                  {c.anchor_reference && !['my','his','her','their'].includes(c.anchor_reference.toLowerCase())
                    ? c.anchor_reference + "'s " : ''}
                  {c.relational_term_raw || c.relational_term || 'relationship'}
                </span>
                {c.is_plural && (
                  <span style={{ color: C.warning, marginLeft: 6, fontSize: 11, fontWeight: 600 }}>
                    (multiple — link each person)
                  </span>
                )}
                {c.anchor_contact ? (
                  <span style={{ color: C.textDim, fontSize: 11, marginLeft: 8, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    anchor: {c.anchor_contact.canonical_name}
                    <button onClick={(e) => { e.stopPropagation(); setEditingAnchorId(editingAnchorId === c.id ? null : c.id); setAnchorSearch(''); setAnchorResults([]); }}
                      style={{ fontSize: 10, background: 'none', border: 'none', color: C.accent, cursor: 'pointer', padding: '0 2px' }}
                      title="Edit anchor">{editingAnchorId === c.id ? '\u2716' : '\u270E'}</button>
                  </span>
                ) : (
                  <button onClick={() => { setEditingAnchorId(editingAnchorId === c.id ? null : c.id); setAnchorSearch(''); setAnchorResults([]); }}
                    style={{ fontSize: 11, color: C.accent, background: 'none', border: 'none', cursor: 'pointer', marginLeft: 8 }}>
                    set anchor
                  </button>
                )}
                {/* Anchor edit search dropdown (Bug 5) */}
                {editingAnchorId === c.id && (
                  <div style={{ marginTop: 6, padding: 6, background: C.bg, borderRadius: 4 }}>
                    <input value={anchorSearch}
                      onChange={async (e) => {
                        setAnchorSearch(e.target.value);
                        if (e.target.value.length >= 2) {
                          try {
                            const r = await searchContactsFn(e.target.value, 8);
                            setAnchorResults(r);
                          } catch {}
                        } else { setAnchorResults([]); }
                      }}
                      placeholder="Search for anchor person..."
                      autoFocus
                      style={{ width: '100%', padding: '4px 8px', fontSize: 12, borderRadius: 3,
                        background: C.card, color: C.text, border: '1px solid ' + C.border, outline: 'none', boxSizing: 'border-box' }} />
                    {anchorResults.map(r => (
                      <div key={r.id}
                        onClick={() => {
                          // Update the claim's anchor_contact in local state
                          setClaims(prev => prev.map(cl =>
                            cl.id === c.id ? { ...cl, anchor_contact: { id: r.id, canonical_name: r.canonical_name }, anchor_reference: r.canonical_name } : cl
                          ));
                          setEditingAnchorId(null);
                          setAnchorSearch('');
                          setAnchorResults([]);
                        }}
                        style={{ padding: '4px 8px', fontSize: 12, color: C.text, cursor: 'pointer', borderRadius: 3 }}
                        onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                        {r.canonical_name}
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ fontSize: 12, color: C.textMuted, marginTop: 4 }}>
                  {c.claim_text?.slice(0, 140)}{c.claim_text?.length > 140 ? '...' : ''}
                </div>

                {/* Show already-linked people for this claim */}
                {linked.length > 0 && (
                  <div style={{ marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {linked.map((p, i) => (
                      <span key={i} style={{
                        fontSize: 11, padding: '2px 8px', borderRadius: 10,
                        background: C.success + '22', color: C.success,
                      }}>✓ {p.name}</span>
                    ))}
                  </div>
                )}
              </div>

              <button
                onClick={() => setLinkingId(linkingId === c.id ? null : c.id)}
                style={{
                  padding: '4px 10px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                  background: '#ec4899' + '22', color: '#ec4899',
                  border: '1px solid ' + '#ec4899' + '44', whiteSpace: 'nowrap',
                }}>
                {c.is_plural ? 'Link Person' : 'Link'}
              </button>
            </div>

            {/* Search dropdown */}
            {linkingId === c.id && (
              <div style={{ marginTop: 8, padding: 8, background: C.bg, borderRadius: 4 }}>
                <input
                  type="text" placeholder="Search contacts..."
                  value={linkSearch} onChange={e => handleSearch(e.target.value)}
                  autoFocus
                  style={{
                    width: '100%', padding: '6px 10px', fontSize: 13, borderRadius: 4,
                    background: C.card, color: C.text, border: '1px solid ' + C.border,
                    outline: 'none', boxSizing: 'border-box',
                  }}
                />
                {linkResults.length > 0 && (
                  <div style={{ marginTop: 4, maxHeight: 150, overflowY: 'auto' }}>
                    {linkResults.map(r => (
                      <div key={r.id}
                        onClick={() => handleLink(c, r.id)}
                        style={{
                          padding: '6px 10px', cursor: 'pointer', fontSize: 13,
                          color: C.text, borderRadius: 4,
                        }}
                        onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      >
                        {r.canonical_name}
                        {r.email && <span style={{ color: C.textDim, marginLeft: 8, fontSize: 11 }}>{r.email}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}


export function PeopleReviewBanner({
  conversationId, contacts, onResolved, onPeopleLoaded,
  initialPeople,
  loadPeopleFn = api.conversationPeople,
  confirmPersonFn = api.confirmPerson,
  skipPersonFn = api.skipPerson,
  unskipPersonFn = api.unskipPerson,
  dismissPersonFn = api.dismissPerson,
  searchContactsFn = api.searchContacts,
  linkProvisionalFn = api.linkProvisional,
  dismissProvisionalFn = api.dismissProvisional,
  confirmProvisionalFn = api.confirmProvisional,
}) {
  const [people, setPeople] = useState(initialPeople || []);
  const [loading, setLoading] = useState(!initialPeople);
  const [expanded, setExpanded] = useState(false);
  const [linkingName, setLinkingName] = useState(null);
  const [linkSearch, setLinkSearch] = useState('');
  const [linkResults, setLinkResults] = useState([]);
  const [editingName, setEditingName] = useState(null);
  const [editForm, setEditForm] = useState({ name: '', email: '', phone: '', aliases: '' });
  const [actionLoading, setActionLoading] = useState(null);

  const fetchPeople = useCallback(() => {
    if (initialPeople) return;
    loadPeopleFn(conversationId)
      .then(d => {
        const ppl = d.people || [];
        setPeople(ppl);
        // Report counts to parent
        const yellow = ppl.filter(p => p.status === 'auto_resolved').length;
        const red = ppl.filter(p => p.status === 'provisional' || p.status === 'unresolved').length;
        if (onPeopleLoaded) onPeopleLoaded({ yellow, red, total: ppl.length });
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conversationId, onPeopleLoaded]);

  useEffect(() => { fetchPeople(); }, [fetchPeople]);

  if (loading) return null;
  if (people.length === 0) return null;

  const nonSelf = people.filter(p => !p.is_self);
  const selfPeople = people.filter(p => p.is_self);
  const yellowPeople = nonSelf.filter(p => p.status === 'auto_resolved');
  const redPeople = nonSelf.filter(p => p.status === 'provisional' || p.status === 'unresolved');
  const greenPeople = nonSelf.filter(p => p.status === 'confirmed');
  const skippedPeople = nonSelf.filter(p => p.status === 'skipped');
  const allGreen = yellowPeople.length === 0 && redPeople.length === 0 && skippedPeople.length === 0;

  const handleConfirm = async (person) => {
    setActionLoading(person.original_name);
    try {
      await confirmPersonFn(conversationId, person.original_name, person.entity_id);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Confirm failed', e); }
    setActionLoading(null);
  };

  const handleSkip = async (person) => {
    setActionLoading(person.original_name);
    try {
      await skipPersonFn(conversationId, person.original_name, person.entity_id || null);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Skip failed', e); }
    setActionLoading(null);
  };

  const handleUnskip = async (person) => {
    setActionLoading(person.original_name);
    try {
      await unskipPersonFn(conversationId, person.original_name, person.entity_id || null);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Unskip failed', e); }
    setActionLoading(null);
  };

  const handleDismissPerson = async (person) => {
    setActionLoading(person.original_name);
    try {
      await dismissPersonFn(conversationId, person.original_name, person.entity_id || null);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Dismiss person failed', e); }
    setActionLoading(null);
  };

  const handleSearch = async (q) => {
    setLinkSearch(q);
    if (q.length < 2) { setLinkResults([]); return; }
    try {
      const results = await searchContactsFn(q, 10);
      setLinkResults(results.filter(c => c.is_confirmed !== 0));
    } catch { setLinkResults([]); }
  };

  const handleLink = async (person, targetId) => {
    setActionLoading(person.original_name);
    try {
      if (person.entity_id && person.is_provisional) {
        await linkProvisionalFn(person.entity_id, targetId);
      } else {
        // For auto_resolved "change" action, use confirm-person with new entity
        await confirmPersonFn(conversationId, person.original_name, targetId);
      }
      setLinkingName(null);
      setLinkSearch('');
      setLinkResults([]);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Link failed', e); }
    setActionLoading(null);
  };

  const handleDismiss = async (person) => {
    if (!person.entity_id) return;
    setActionLoading(person.original_name);
    try {
      await dismissProvisionalFn(person.entity_id);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Dismiss failed', e); }
    setActionLoading(null);
  };

  const startEdit = (person) => {
    setEditingName(person.original_name);
    setEditForm({
      name: person.canonical_name || person.original_name || '',
      email: '',
      phone: '',
      aliases: '',
    });
  };

  const handleCreateContact = async (person) => {
    if (!person.entity_id) return;
    setActionLoading(person.original_name);
    try {
      await confirmProvisionalFn(
        person.entity_id,
        editForm.name || null,
        false,
        null,
        editForm.email || null,
        editForm.phone || null,
        editForm.aliases || null,
      );
      setEditingName(null);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Create contact failed', e); }
    setActionLoading(null);
  };

  // Determine banner color based on state
  const bannerColor = allGreen ? C.success : (redPeople.length > 0 ? C.warning : C.warning);
  const inputStyle = {
    width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4,
    background: C.bg, color: C.text, border: '1px solid ' + C.border,
    outline: 'none', boxSizing: 'border-box',
  };

  // All green collapsed state
  if (allGreen && !expanded) {
    return (
      <div style={{
        ...cardStyle, marginBottom: 16, cursor: 'pointer',
        borderColor: C.success + '44',
        background: C.success + '08',
      }} onClick={() => setExpanded(true)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{'\u{1F465}'}</span>
          <span style={{ color: C.success, fontWeight: 600, fontSize: 13 }}>
            {people.length} people {'\u2014'} all resolved {'\u2705'}
          </span>
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto' }}>click to expand</span>
        </div>
      </div>
    );
  }

  const renderStatusDot = (status) => {
    const color = status === 'confirmed' ? C.success : status === 'auto_resolved' ? C.warning : status === 'skipped' ? C.textDim : C.danger;
    return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />;
  };

  const renderPersonRow = (person) => {
    const isYellow = person.status === 'auto_resolved';
    const isRed = person.status === 'provisional' || person.status === 'unresolved';
    const isGreen = person.status === 'confirmed';
    const isSkipped = person.status === 'skipped';
    const isDismissed = person.status === 'dismissed';
    const isLoading = actionLoading === person.original_name;
    const isLinking = linkingName === person.original_name;
    const isEditing = editingName === person.original_name;

    return (
      <div key={person.original_name + (person.entity_id || '')} style={{
        padding: (isGreen || isSkipped || isDismissed) ? '6px 12px' : '10px 12px', marginBottom: 6,
        background: (isGreen || isSkipped || isDismissed) ? 'transparent' : C.card,
        borderRadius: 6,
        border: (isGreen || isSkipped || isDismissed) ? 'none' : '1px solid ' + C.border,
        opacity: isLoading ? 0.6 : (isSkipped || isDismissed) ? 0.5 : 1,
      }}>
        {isEditing ? (
          /* Create contact edit form */
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Full Name *</label>
                <input value={editForm.name}
                  onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                  style={inputStyle} placeholder="First Last" />
              </div>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Email</label>
                <input value={editForm.email}
                  onChange={e => setEditForm(f => ({ ...f, email: e.target.value }))}
                  style={inputStyle} placeholder="email@example.com" type="email" />
              </div>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Phone</label>
                <input value={editForm.phone}
                  onChange={e => setEditForm(f => ({ ...f, phone: e.target.value }))}
                  style={inputStyle} placeholder="(555) 123-4567" type="tel" />
              </div>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Aliases (semicolon-separated)</label>
                <input value={editForm.aliases}
                  onChange={e => setEditForm(f => ({ ...f, aliases: e.target.value }))}
                  style={inputStyle} placeholder="Nick; Nickname" />
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button onClick={() => handleCreateContact(person)}
                disabled={!editForm.name.trim()}
                style={{
                  padding: '5px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                  background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
                  opacity: editForm.name.trim() ? 1 : 0.4,
                }}>Create Contact</button>
              <button onClick={() => setEditingName(null)}
                style={{
                  padding: '5px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                  background: C.card, color: C.textDim, border: '1px solid ' + C.border,
                }}>Cancel</button>
            </div>
          </div>
        ) : (
          /* Normal row */
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                {renderStatusDot(person.status)}
                <span style={{
                  color: (isGreen || isSkipped || isDismissed) ? C.textMuted : C.text,
                  fontWeight: (isGreen || isSkipped || isDismissed) ? 400 : 600,
                  fontSize: (isGreen || isSkipped || isDismissed) ? 12 : 14,
                }}>
                  {isGreen ? '\u2713 ' : isSkipped ? '\u23ED ' : isDismissed ? '\u2717 ' : ''}{person.canonical_name || person.original_name}
                </span>
                {isYellow && person.original_name !== person.canonical_name && (
                  <span style={{ color: C.textDim, fontSize: 11 }}>
                    (matched from "{person.original_name}")
                  </span>
                )}
                {isRed && (
                  <span style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 3, fontWeight: 600,
                    background: C.danger + '22', color: C.danger,
                  }}>
                    {person.status}
                  </span>
                )}
                {(person.claim_count > 0 && !isGreen || person.unlinked_claim_count > 0) && (
                  <span style={{ color: C.textDim, fontSize: 11 }}>
                    ({person.claim_count} claim{person.claim_count !== 1 ? 's' : ''}{person.unlinked_claim_count > 0 ? `, ${person.unlinked_claim_count} unlinked` : ''})
                  </span>
                )}
              </div>

              {/* Action buttons */}
              <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                {isYellow && (
                  <>
                    <button onClick={() => handleConfirm(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
                      }}>{'\u2713'} Confirm</button>
                    <button onClick={() => { setLinkingName(isLinking ? null : person.original_name); setLinkSearch(''); setLinkResults([]); }}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                      }}>Change</button>
                    <button onClick={() => handleSkip(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.card, color: C.textDim, border: '1px solid ' + C.border,
                      }}>{'\u2717'} Skip</button>
                  </>
                )}
                {isRed && person.status === 'provisional' && (
                  <>
                    <button onClick={() => { setLinkingName(isLinking ? null : person.original_name); setLinkSearch(''); setLinkResults([]); }}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                      }}>Link to Existing</button>
                    <button onClick={() => startEdit(person)}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
                      }}>Create Contact</button>
                    <button onClick={() => handleSkip(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.card, color: C.textDim, border: '1px solid ' + C.border,
                      }}>Skip</button>
                    <button onClick={() => handleDismissPerson(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.danger + '22', color: C.danger, border: '1px solid ' + C.danger + '44',
                      }}>Dismiss</button>
                  </>
                )}
                {isRed && person.status === 'unresolved' && (
                  <>
                    <button onClick={() => { setLinkingName(isLinking ? null : person.original_name); setLinkSearch(''); setLinkResults([]); }}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                      }}>Link to Existing</button>
                    <button onClick={() => handleSkip(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.card, color: C.textDim, border: '1px solid ' + C.border,
                      }}>Skip</button>
                    <button onClick={() => handleDismissPerson(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.danger + '22', color: C.danger, border: '1px solid ' + C.danger + '44',
                      }}>Dismiss</button>
                  </>
                )}
                {isSkipped && (
                  <button onClick={() => handleUnskip(person)} disabled={isLoading}
                    style={{
                      padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                      background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                    }}>Undo Skip</button>
                )}
                {isDismissed && (
                  <button onClick={() => handleUnskip(person)} disabled={isLoading}
                    style={{
                      padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                      background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                    }}>Undo Dismiss</button>
                )}
              </div>
            </div>

            {/* Search dropdown for linking */}
            {isLinking && (
              <div style={{ marginTop: 8, padding: 8, background: C.bg, borderRadius: 4 }}>
                <input type="text" placeholder="Search contacts..."
                  value={linkSearch} onChange={e => handleSearch(e.target.value)}
                  autoFocus
                  style={{
                    width: '100%', padding: '6px 10px', fontSize: 13, borderRadius: 4,
                    background: C.card, color: C.text, border: '1px solid ' + C.border,
                    outline: 'none', boxSizing: 'border-box',
                  }} />
                {linkResults.length > 0 && (
                  <div style={{ marginTop: 4, maxHeight: 150, overflowY: 'auto' }}>
                    {linkResults.map(r => (
                      <div key={r.id}
                        onClick={() => handleLink(person, r.id)}
                        style={{
                          padding: '6px 10px', cursor: 'pointer', fontSize: 13,
                          color: C.text, borderRadius: 4,
                        }}
                        onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                        {r.canonical_name}
                        {r.email && <span style={{ color: C.textDim, marginLeft: 8, fontSize: 11 }}>{r.email}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: bannerColor + '44',
      background: bannerColor + '08',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: allGreen ? 0 : 12 }}>
        <span style={{ fontSize: 14 }}>{'\u{1F465}'}</span>
        <span style={{ color: bannerColor, fontWeight: 600, fontSize: 14 }}>
          People ({people.length})
        </span>
        {yellowPeople.length > 0 && (
          <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3, background: C.warning + '22', color: C.warning }}>
            {yellowPeople.length} auto-resolved
          </span>
        )}
        {redPeople.length > 0 && (
          <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3, background: C.danger + '22', color: C.danger }}>
            {redPeople.length} needs attention
          </span>
        )}
        {allGreen && (
          <span style={{ color: C.textDim, fontSize: 11, cursor: 'pointer' }}
            onClick={() => setExpanded(false)}>
            {'\u2014'} all resolved {'\u2705'} (click to collapse)
          </span>
        )}
      </div>

      {/* Red people first (need attention) */}
      {redPeople.map(renderPersonRow)}

      {/* Yellow people (auto-resolved, need confirmation) */}
      {yellowPeople.map(renderPersonRow)}

      {/* Green people (compact) */}
      {(allGreen || expanded || greenPeople.length <= 3) && greenPeople.map(renderPersonRow)}
      {!allGreen && !expanded && greenPeople.length > 3 && (
        <div style={{ fontSize: 11, color: C.textDim, padding: '4px 12px', cursor: 'pointer' }}
          onClick={() => setExpanded(true)}>
          + {greenPeople.length} confirmed people (click to show)
        </div>
      )}

      {/* Skipped people */}
      {skippedPeople.map(renderPersonRow)}

      {/* Self at the bottom */}
      {selfPeople.map(person => (
        <div key="self" style={{ padding: '4px 12px', fontSize: 12, color: C.textDim }}>
          {'\u{1F464}'} {person.canonical_name || person.original_name} (you)
        </div>
      ))}
    </div>
  );
}


// ═══════════════════════════════════════════════════════
// ROUTING PREVIEW (Layer 3)
// ═══════════════════════════════════════════════════════
const OBJECT_TYPE_LABELS = {
  standing_offers: 'Standing Offers',
  scheduling_leads: 'Scheduling Leads',
  graph_edges: 'Graph Edges',
  contact_commitments: 'Contact Commitments',
  policy_positions: 'Policy Positions',
  my_commitments: 'My Commitments',
  follow_ups: 'Follow-Ups',
};

export function RoutingPreview({ conversationId, refreshKey }) {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [expandedTypes, setExpandedTypes] = useState({});

  useEffect(() => {
    setLoading(true);
    api.routingPreview(conversationId)
      .then(d => {
        setPreview(d);
        // Auto-expand if there are blocked items
        if (d.blocked_count > 0) setExpanded(true);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conversationId, refreshKey]);

  if (loading || !preview) return null;
  if (preview.ready_count === 0 && preview.blocked_count === 0) return null;

  const totalObjects = preview.ready_count + preview.blocked_count + (preview.skipped_count || 0);
  const allReady = preview.blocked_count === 0 && (preview.skipped_count || 0) === 0;
  const objectTypes = Object.keys(preview.objects || {});

  const toggleType = (type) => {
    setExpandedTypes(prev => ({ ...prev, [type]: !prev[type] }));
  };

  // Collapsed state: all ready
  if (allReady && !expanded) {
    return (
      <div style={{
        ...cardStyle, marginBottom: 16, cursor: 'pointer',
        borderColor: C.success + '33',
        background: C.success + '06',
      }} onClick={() => setExpanded(true)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{'\u{1F4E6}'}</span>
          <span style={{ color: C.success, fontWeight: 600, fontSize: 13 }}>
            {'\u2705'} {totalObjects} object{totalObjects !== 1 ? 's' : ''} ready to route
          </span>
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto' }}>click to expand</span>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: allReady ? C.success + '33' : C.border,
      background: allReady ? C.success + '06' : C.card,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 14 }}>{'\u{1F4E6}'}</span>
        <span style={{ fontWeight: 600, fontSize: 14, color: C.text }}>
          Routing Preview
        </span>
        <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 3, background: C.success + '22', color: C.success }}>
          {preview.ready_count} ready
        </span>
        {preview.blocked_count > 0 && (
          <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 3, background: C.danger + '22', color: C.danger }}>
            {preview.blocked_count} blocked
          </span>
        )}
        {(preview.skipped_count || 0) > 0 && (
          <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 3, background: C.warning + '22', color: C.warning }}>
            {preview.skipped_count} skipped
          </span>
        )}
        {allReady && (
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto', cursor: 'pointer' }}
            onClick={() => setExpanded(false)}>
            collapse
          </span>
        )}
      </div>

      {objectTypes.map(type => {
        const items = preview.objects[type];
        const label = OBJECT_TYPE_LABELS[type] || type.replace(/_/g, ' ');
        const readyCount = items.filter(i => i.status === 'ready').length;
        const blockedCount = items.filter(i => i.status === 'blocked').length;
        const skippedCount = items.filter(i => i.status === 'skipped').length;
        const isTypeExpanded = expandedTypes[type] !== undefined ? expandedTypes[type] : blockedCount > 0;

        return (
          <div key={type} style={{ marginBottom: 8 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '6px 0',
              cursor: 'pointer', userSelect: 'none',
            }} onClick={() => toggleType(type)}>
              <span style={{ fontSize: 11, color: C.textDim }}>{isTypeExpanded ? '\u25BC' : '\u25B6'}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.text, textTransform: 'capitalize' }}>
                {label}
              </span>
              <span style={{ fontSize: 11, color: C.textDim }}>({items.length})</span>
              {blockedCount > 0 && (
                <span style={{ fontSize: 10, padding: '0 5px', borderRadius: 3, background: C.danger + '22', color: C.danger }}>
                  {blockedCount} blocked
                </span>
              )}
            </div>

            {isTypeExpanded && (
              <div style={{ paddingLeft: 16 }}>
                {items.map((item, idx) => {
                  const isBlocked = item.status === 'blocked';
                  const isSkipped = item.status === 'skipped';
                  return (
                    <div key={idx} style={{
                      display: 'flex', alignItems: 'flex-start', gap: 6, padding: '4px 0',
                      fontSize: 12, opacity: isSkipped ? 0.5 : 1,
                    }}>
                      <span style={{ flexShrink: 0, marginTop: 1 }}>
                        {isBlocked ? '\u{1F534}' : isSkipped ? '\u23ED\uFE0F' : '\u2705'}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ color: isBlocked ? C.text : C.textMuted }}>
                          {item.summary || '(no summary)'}
                        </span>
                        {isBlocked && item.blocker && (
                          <div style={{ fontSize: 11, color: C.danger, marginTop: 2 }}>
                            {'\u2514'} {item.blocker}
                          </div>
                        )}
                        {/* Show people chips */}
                        {item.people && item.people.length > 0 && (
                          <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginTop: 3 }}>
                            {item.people.map((p, pi) => (
                              <span key={pi} style={{
                                fontSize: 10, padding: '1px 5px', borderRadius: 3,
                                background: p.skipped ? (C.warning + '15') : p.resolved ? (C.success + '15') : (C.danger + '15'),
                                color: p.skipped ? C.warning : p.resolved ? C.success : C.danger,
                              }}>
                                {p.skipped ? '\u23ED ' : p.resolved ? '\u2713 ' : '\u2717 '}
                                {p.canonical_name || p.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}


export function Chip({ label, value, color }) {
  return (
    <span style={{ fontSize: 12, padding: '4px 10px', borderRadius: 4,
      background: `${color || C.accent}15`, color: C.textMuted }}>
      {label}: <strong style={{ color: color || C.text }}>{value}</strong>
    </span>
  );
}
