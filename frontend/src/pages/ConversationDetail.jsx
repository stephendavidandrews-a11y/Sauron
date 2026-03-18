import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api';
import { safeCall, friendlyError } from '../utils/apiResult';
import { useToast } from '../components/StatusToast';
import { fetchRoutingSummary, fetchPendingRoutes } from '../api';
import TextReplaceCascade from '../components/TextReplaceCascade';
import { C } from "../utils/colors";
import { cardStyle, Chip } from '../components/review/styles';
import { EpisodesTab } from '../components/review/tabs/EpisodesTab';
import { ClaimsTab } from '../components/review/tabs/ClaimsTab';
import { TranscriptTab } from '../components/review/tabs/TranscriptTab';
import { SummaryTab, RawTab } from '../components/review/tabs/SummaryTab';
import { PeopleReviewBanner } from '../components/review/banners/PeopleReviewBanner';
import { ObjectsReviewBanner } from '../components/review/banners/ObjectsReviewBanner';
import { RelationalReferencesBanner } from '../components/review/banners/RelationalReferencesBanner';
import { GraphEdgeReviewBanner } from '../components/review/banners/GraphEdgeReviewBanner';
import { ErrorBoundary } from '../components/review/ErrorBoundary';
import { RoutingPreview } from '../components/review/banners/RoutingPreview';
import { BulkReassignModal } from '../components/review/BulkReassignModal';

function RoutingChip({ summary, expanded, onToggle }) {
  const rs = summary;
  const chipMap = {
    success: { bg: '#10b98122', color: '#10b981', border: '#10b98144', label: '✓ Routed' },
    success_with_partial_secondary_loss: { bg: '#f59e0b22', color: '#f59e0b', border: '#f59e0b44', label: '⚠ Partial' },
    failed: { bg: '#ef444422', color: '#ef4444', border: '#ef444444', label: '✗ Failed' },
  };
  const chip = rs ? (chipMap[rs.final_state] || chipMap.failed) : null;
  const isExpandable = rs && rs.final_state !== 'success';
  return (
    <div style={{ marginTop: 6 }}>
      <span
        onClick={() => isExpandable && onToggle()}
        style={{
          display: 'inline-block', fontSize: 11, padding: '2px 10px', borderRadius: 12,
          background: chip ? chip.bg : '#6b728022', color: chip ? chip.color : '#6b7280',
          border: '1px solid ' + (chip ? chip.border : '#6b728044'),
          cursor: isExpandable ? 'pointer' : 'default', fontWeight: 500,
        }}>
        {chip ? chip.label : '— Not routed'}
      </span>
      {expanded && rs && (
        <div style={{ background: '#1a1f2e', borderRadius: 8, padding: 12, marginTop: 8, fontSize: 13 }}>
          <div style={{ marginBottom: 8, color: '#e5e7eb' }}>
            <strong>Core lanes:</strong> {(rs.core_lanes || []).filter(l => l.status === 'success').length}/{(rs.core_lanes || []).length} succeeded
          </div>
          <div style={{ marginBottom: 8, color: '#e5e7eb' }}>
            <strong>Secondary lanes:</strong> {(rs.secondary_lanes || []).filter(l => l.status === 'success').length}/{(rs.secondary_lanes || []).length} succeeded
          </div>
          {(rs.secondary_lanes || []).filter(l => l.status !== 'success').map((lane, i) => (
            <div key={i} style={{ color: lane.status === 'failed' ? '#ef4444' : '#f59e0b', marginLeft: 12, marginBottom: 4 }}>
              {lane.name}: {lane.status} {lane.reason ? '— ' + lane.reason : ''}
            </div>
          ))}
          {(rs.core_lanes || []).filter(l => l.status !== 'success').map((lane, i) => (
            <div key={'c' + i} style={{ color: '#ef4444', marginLeft: 12, marginBottom: 4 }}>
              {lane.name}: {lane.status} {lane.reason ? '— ' + lane.reason : ''}
            </div>
          ))}
          {rs.pending_entities && rs.pending_entities.length > 0 && (
            <div style={{ marginTop: 8, color: '#a78bfa' }}>
              Pending: {rs.pending_entities.join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ConversationDetail() {
  const { id } = useParams();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [tab, setTab] = useState('episodes');
  const [reprocessing, setReprocessing] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [reviewStats, setReviewStats] = useState(null);
  const [contactsList, setContactsList] = useState([]);
  const [showReassignModal, setShowReassignModal] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [textReplaceTarget, setTextReplaceTarget] = useState(null);
  const [peopleStatus, setPeopleStatus] = useState(null);
  const [claims, setClaims] = useState([]);

  // Routing status for degraded-state visibility
  const [routingSummary, setRoutingSummary] = useState(null);
  const [routingExpanded, setRoutingExpanded] = useState(false);
  useEffect(() => {
    fetchRoutingSummary(id).then(summaries => {
      if (summaries.length > 0) setRoutingSummary(summaries[0]);
    });
  }, [id]);

  const reload = useCallback(() => {
    setLoading(true);
    setRefreshKey(k => k + 1);
    api.conversation(id).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    reload();
    api.contacts(500).then(d => setContactsList(d.contacts || [])).catch(() => {});
  }, [id]);

  // Pending routes by entity (for people review)
  const [pendingEntities, setPendingEntities] = useState([]);
  useEffect(() => {
    fetchPendingRoutes('entity').then(items => {
      setPendingEntities(items || []);
    });
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

  const handleActionError = useCallback((msg) => {
    setActionError(msg);
    setTimeout(() => setActionError(null), 6000);
  }, []);

  const handleReprocess = async () => {
    setReprocessing(true);
    const result = await safeCall(() => api.pipelineProcess(id));
    if (result.ok) {
      toast.info('Reprocessing started — reloading in 2s');
      setTimeout(() => { reload(); setReprocessing(false); }, 2000);
    } else {
      toast.error('Reprocess failed: ' + friendlyError(result));
      setReprocessing(false);
    }
  };

  const handleMarkReviewed = async () => {
    setReviewing(true);
    try {
      const result = await api.markReviewed(id);
      setReviewed(true);
      if (result.stats) {
        setReviewStats(result.stats);
      }
    } catch (e) {
      console.error('Review failed', e);
      handleActionError('Mark as reviewed failed \u2014 please retry');
    }
    setReviewing(false);
  };

  const [discarding, setDiscarding] = useState(false);
  const handleDiscard = async () => {
    if (!window.confirm('Discard this conversation? It will be removed from all review queues.')) return;
    setDiscarding(true);
    const discardResult = await safeCall(() => api.discardConversation(id, 'discarded_from_review'));
    if (discardResult.ok) {
      window.location.href = '/review';
    } else {
      toast.error('Discard failed: ' + friendlyError(discardResult));
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
          {/* Routing status chip */}
          <RoutingChip summary={routingSummary} expanded={routingExpanded} onToggle={() => setRoutingExpanded(e => !e)} />
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
          <button onClick={() => setTextReplaceTarget({ findText: '', replaceWith: '' })}
            aria-label="Fix text in transcript" style={{ padding: '8px 16px', background: '#6b7280', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
            Fix Text
          </button>
        </div>
      </div>

      {/* Text replace cascade (top-level, triggered by Fix Text button or people review) */}
      {textReplaceTarget && (
        <div style={{ margin: '0 0 16px 0' }}>
          <TextReplaceCascade
            conversationId={id}
            defaultFindText={textReplaceTarget.findText}
            defaultReplaceWith={textReplaceTarget.replaceWith}
            onComplete={() => { setTextReplaceTarget(null); reload(); }}
            onDismiss={() => setTextReplaceTarget(null)}
          />
        </div>
      )}

      {/* Metadata chips */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0 20px' }}>
        {convo.duration_seconds && <Chip label="Duration" value={`${Math.round(convo.duration_seconds / 60)}m`} />}
        {convo.context_classification && <Chip label="Context" value={convo.context_classification} />}
        {synthesis.word_voice_alignment && (
          <Chip label="Voice" value={synthesis.word_voice_alignment}
            color={synthesis.word_voice_alignment === 'misaligned' ? C.danger : C.success} />
        )}
      </div>

      {/* Action error banner */}
      {actionError && (
        <div data-testid="action-error-banner" style={{
          padding: '8px 14px', marginBottom: 12, borderRadius: 6,
          background: C.danger + '18', border: '1px solid ' + C.danger + '44',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ color: C.danger, fontSize: 13, fontWeight: 500 }}>{actionError}</span>
          <button onClick={() => setActionError(null)} aria-label="Dismiss error" style={{
            background: 'none', border: 'none', color: C.danger, cursor: 'pointer',
            fontSize: 16, padding: '0 4px', lineHeight: 1,
          }}>{'\u2715'}</button>
        </div>
      )}

      {/* Layer 1: People resolution */}
      <ErrorBoundary label="People Review"><PeopleReviewBanner key={`people-${refreshKey}`} conversationId={id} contacts={contactsList} onResolved={reload} onPeopleLoaded={setPeopleStatus} pendingEntities={pendingEntities} textReplaceTarget={textReplaceTarget} setTextReplaceTarget={setTextReplaceTarget} /></ErrorBoundary>

      {/* Layer 1.5: Non-person entities (orgs, legislation, topics) */}
      <ErrorBoundary label="Objects Review"><ObjectsReviewBanner key={`objects-${refreshKey}`} conversationId={id} onResolved={reload} /></ErrorBoundary>

      {/* Layer 2: Relational references (unchanged) */}
      <ErrorBoundary label="Relational References"><RelationalReferencesBanner key={`rel-${refreshKey}`} conversationId={id} contacts={contactsList} onResolved={reload} /></ErrorBoundary>

      {/* Layer 3: Graph edge review */}
      <ErrorBoundary label="Graph Edges"><GraphEdgeReviewBanner key={`edges-${refreshKey}`} conversationId={id} refreshKey={refreshKey} /></ErrorBoundary>

      {/* Layer 4: Routing preview */}
      <ErrorBoundary label="Routing Preview"><RoutingPreview key={`routing-${refreshKey}`} conversationId={id} refreshKey={refreshKey} /></ErrorBoundary>

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

      {tab === 'episodes' && <ErrorBoundary label="Episodes"><EpisodesTab episodes={episodes} claims={claims} conversationId={id} contacts={contactsList} updateClaim={updateClaim} addClaimToState={addClaimToState} onActionError={handleActionError} /></ErrorBoundary>}
      {tab === 'transcript' && <ErrorBoundary label="Transcript"><TranscriptTab transcript={transcript} conversationId={id} contacts={contactsList} /></ErrorBoundary>}
      {tab === 'claims' && <ErrorBoundary label="Claims"><ClaimsTab claims={claims} conversationId={id} contacts={contactsList} updateClaim={updateClaim} onActionError={handleActionError} /></ErrorBoundary>}
      {tab === 'summary' && <ErrorBoundary label="Summary"><SummaryTab synthesis={synthesis} beliefUpdates={beliefUpdates} claims={claims} /></ErrorBoundary>}
      {tab === 'raw' && <ErrorBoundary label="Raw"><RawTab extraction={parsedExtraction} /></ErrorBoundary>}

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
// Re-exports for Storybook compatibility
// Stories import from '../../pages/ConversationDetail'
// ═══════════════════════════════════════════════════════
export { C } from '../utils/colors';
export { cardStyle, Chip } from '../components/review/styles';
export { claimTypeColors, errorTypes } from '../components/review/styles';
export { EpisodesTab } from '../components/review/tabs/EpisodesTab';
export { ClaimsTab } from '../components/review/tabs/ClaimsTab';
export { TranscriptTab } from '../components/review/tabs/TranscriptTab';
export { SummaryTab, CommitmentRow, RawTab } from '../components/review/tabs/SummaryTab';
export { ClaimRow } from '../components/review/claims/ClaimRow';
export { ClaimTextWithOverrides } from '../components/review/claims/ClaimTextWithOverrides';
export { AddClaimForm } from '../components/review/claims/AddClaimForm';
export { CommitmentEditPanel } from '../components/review/claims/CommitmentEditPanel';
export { ErrorTypeDropdown } from '../components/review/claims/ErrorTypeDropdown';
export { EntityChips } from '../components/review/claims/EntityChips';
export { PeopleReviewBanner } from '../components/review/banners/PeopleReviewBanner';
export { ObjectsReviewBanner } from '../components/review/banners/ObjectsReviewBanner';
export { RelationalReferencesBanner } from '../components/review/banners/RelationalReferencesBanner';
export { GraphEdgeReviewBanner } from '../components/review/banners/GraphEdgeReviewBanner';
export { RoutingPreview } from '../components/review/banners/RoutingPreview';
export { BulkReassignModal } from '../components/review/BulkReassignModal';
