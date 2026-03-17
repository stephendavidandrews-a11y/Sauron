import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { fetchPendingRoutes, fetchProvisionalOrgs } from '../api';
import { C } from "../utils/colors";
import { relativeTime } from "../utils/time";

import { StatusDot } from '../components/review/StatusDot';
import { QueueBadge } from '../components/review/QueueBadge';
import { QuickPassView } from '../components/review/quickpass/QuickPassView';
import { TriageCard } from '../components/review/triage/TriageCard';
import { DuplicateContactBanner } from '../components/review/triage/DuplicateContactBanner';
import { ProvisionalOrgCard } from '../components/review/orgs/ProvisionalOrgCard';

export default function Review() {
  const [conversations, setConversations] = useState([]);
  const [queueCounts, setQueueCounts] = useState({});
  const [beliefStats, setBeliefStats] = useState(null);
  const [learningData, setLearningData] = useState(null);
  const [proposalCount, setProposalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [quickPassMode, setQuickPassMode] = useState(false);

  // Provisional org suggestions
  const [provOrgs, setProvOrgs] = useState({ groups: [], total: 0 });
  const loadProvOrgs = useCallback(() => {
    fetchProvisionalOrgs('pending').then(setProvOrgs).catch(() => setProvOrgs({ groups: [], total: 0 }));
  }, []);
  useEffect(() => { loadProvOrgs(); }, [loadProvOrgs]);

  // Pending routes for degraded-state visibility
  const [pendingRouteCount, setPendingRouteCount] = useState(0);
  const [pendingEntityCount, setPendingEntityCount] = useState(0);
  const [pendingEntities, setPendingEntities] = useState([]);
  useEffect(() => {
    fetchPendingRoutes("conversation").then(items => {
      setPendingRouteCount(items.length);
    });
    fetchPendingRoutes("entity").then(items => {
      setPendingEntityCount(items.length);
      setPendingEntities(items);
    });
  }, []);

  const handleDiscardConversation = async (convId) => {
    if (!window.confirm('Discard this conversation?')) return;
    try {
      await api.discardConversation(convId);
      loadData();
    } catch (e) {
      console.error('Discard failed:', e);
    }
  };



  const loadData = () => {
    Promise.all([
      api.reviewQueue().catch(() => ({ actionable: [], recently_reviewed: [] })),
      api.queueCounts().catch(() => ({})),
      api.beliefStats().catch(() => null),
      api.learningDashboard().catch(() => null),
      api.pendingResyntheses().catch(() => []),
    ]).then(([reviewData, counts, bStats, lData, proposals]) => {
      const all = [...(reviewData.actionable || []), ...(reviewData.recently_reviewed || [])];
      setConversations(all);
      setQueueCounts(counts);
      if (bStats) setBeliefStats(bStats);
      if (lData) setLearningData(lData);
      setProposalCount((proposals || []).length);
      setLoading(false);
    });
  };

  useEffect(() => { loadData(); }, []);

  // Split conversations by status
  const speakerReview = conversations.filter(c => c.processing_status === 'awaiting_speaker_review');
  const triageReview = conversations.filter(c => c.processing_status === 'triage_rejected');
  const claimReview = conversations.filter(c => c.processing_status === 'awaiting_claim_review');
  const processing = conversations.filter(c =>
    ['transcribing', 'triaging', 'extracting'].includes(c.processing_status)
  );
  const pending = conversations.filter(c => c.processing_status === 'pending');
  const recentlyReviewed = conversations
    .filter(c => c.processing_status === 'completed' && c.reviewed_at)
    .sort((a, b) => new Date(b.reviewed_at) - new Date(a.reviewed_at))
    .slice(0, 10);

  const handlePromote = async (id) => {
    await api.promoteTriage(id);
    loadData();
  };

  const handleArchive = async (id) => {
    await api.archiveTriage(id);
    loadData();
  };

  const sectionStyle = {
    background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20, marginBottom: 20,
  };

  const sectionTitle = {
    fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: 'uppercase',
    letterSpacing: '0.05em', marginBottom: 0,
  };

  const rowStyle = {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '10px 12px', borderRadius: 6, textDecoration: 'none', cursor: 'pointer',
    transition: 'background 0.15s',
  };

  const statusLabels = {
    transcribing: { label: 'transcribing', color: C.warning },
    triaging: { label: 'triaging', color: C.warning },
    extracting: { label: 'extracting', color: C.accent },
  };

  if (loading) {
    return <div style={{ padding: 48, textAlign: 'center', color: C.textDim }}>Loading...</div>;
  }

  const hasNothing = speakerReview.length === 0 && triageReview.length === 0 && claimReview.length === 0
    && processing.length === 0 && pending.length === 0 && recentlyReviewed.length === 0
    && !(beliefStats && beliefStats.total > 0) && provOrgs.total === 0;

  return (
    <div style={{ padding: '24px 0' }} data-testid="review-page">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: C.text, margin: 0 }}>Review</h1>
          {pendingRouteCount > 0 && (
            <span style={{ background: '#7c3aed', color: 'white', borderRadius: 12, padding: '2px 10px', fontSize: 12, display: 'inline-block', marginLeft: 8, verticalAlign: 'middle', fontWeight: 600 }}>
              {pendingRouteCount} pending route{pendingRouteCount !== 1 ? 's' : ''}
            </span>
          )}
          {provOrgs.total > 0 && (
            <span style={{ background: '#f59e0b', color: '#0a0f1a', borderRadius: 12, padding: '2px 10px', fontSize: 12, display: 'inline-block', marginLeft: 8, verticalAlign: 'middle', fontWeight: 600 }}>
              {provOrgs.total} org suggestion{provOrgs.total !== 1 ? 's' : ''}
            </span>
          )}
        {/* Quick Pass toggle + Queue count summary */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {claimReview.length > 0 && (
            <button onClick={() => setQuickPassMode(true)}
              style={{ fontSize: 12, padding: '5px 14px', borderRadius: 4,
                border: `1px solid ${C.accent}50`, background: C.accent + '15',
                color: C.accent, cursor: 'pointer', fontWeight: 600,
                display: 'flex', alignItems: 'center', gap: 6 }}>
              {'⚡'} Quick Pass
            </button>
          )}
        <div style={{ display: 'flex', gap: 12, fontSize: 12, color: C.textDim }}>
          {queueCounts.speaker_review > 0 && (
            <span><span style={{ color: C.purple }}>{'\u25CF'}</span> {queueCounts.speaker_review} speaker</span>
          )}
          {queueCounts.triage_review > 0 && (
            <span><span style={{ color: C.warning }}>{'\u25CF'}</span> {queueCounts.triage_review} triage</span>
          )}
          {queueCounts.claim_review > 0 && (
            <span><span style={{ color: C.accent }}>{'\u25CF'}</span> {queueCounts.claim_review} claims</span>
          )}
        </div>
        </div>
      </div>

      {quickPassMode ? (
        <QuickPassView
          onExit={() => setQuickPassMode(false)}
          onMarkReviewed={() => loadData()} />
      ) : (<>

      <DuplicateContactBanner />

      {/* 1. Speaker Review (purple) */}
      {speakerReview.length > 0 && (
        <div style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3 style={sectionTitle}>Speaker Review</h3>
            <QueueBadge count={speakerReview.length} color={C.purple} />
          </div>
          <p style={{ fontSize: 13, color: C.textDim, marginBottom: 16, marginTop: 4 }}>
            Verify speaker identity before extraction. Unmatched voices need confirmation.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {speakerReview.map(c => (
              <div key={c.id} style={{ ...rowStyle, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <Link to={`/review/${c.id}/speakers`} style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, textDecoration: 'none' }}>
                  <StatusDot color={C.purple} />
                  <span style={{ color: C.text, fontSize: 14 }}>
                    {c.manual_note || c.title || (c.source + " capture")}
                    {c.duration_seconds ? ` — ${Math.round(c.duration_seconds / 60)}min` : ''}
                  </span>
                </Link>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ color: C.textDim, fontSize: 12 }}>
                    {relativeTime(c.captured_at || c.created_at)}
                  </span>
                  <button onClick={() => handleDiscardConversation(c.id)}
                    style={{ fontSize: 10, padding: '2px 8px', borderRadius: 3,
                      border: '1px solid ' + C.danger + '33', background: 'transparent',
                      color: C.danger, cursor: 'pointer', opacity: 0.7 }}
                    title="Discard this conversation">✗</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 2. Triage Check (yellow/amber) */}
      {triageReview.length > 0 && (
        <div style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3 style={sectionTitle}>Triage Check</h3>
            <QueueBadge count={triageReview.length} color={C.warning} />
          </div>
          <p style={{ fontSize: 13, color: C.textDim, marginBottom: 16, marginTop: 4 }}>
            Conversations triaged as low-value. Promote to full extraction or archive.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {triageReview.map(c => (
              <TriageCard key={c.id} convo={c} onPromote={handlePromote} onArchive={handleArchive} onDiscard={handleDiscardConversation} />
            ))}
          </div>
        </div>
      )}

      {/* 3. Claim Review (blue) */}
      {claimReview.length > 0 && (
        <div style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3 style={sectionTitle}>Claim Review</h3>
            <QueueBadge count={claimReview.length} color={C.accent} />
          </div>
          <p style={{ fontSize: 13, color: C.textDim, marginBottom: 16, marginTop: 4 }}>
            Review extracted episodes and claims. Approve, edit, or flag before routing.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {claimReview.map(c => (
              <div key={c.id} style={{ ...rowStyle, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <Link to={`/review/${c.id}`} style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, textDecoration: 'none' }}>
                  <StatusDot color={C.accent} />
                  <span style={{ color: C.text, fontSize: 14 }}>
                    {c.manual_note || c.title || (c.source + " capture")}
                    {c.duration_seconds ? ` — ${Math.round(c.duration_seconds / 60)}min` : ''}
                  </span>
                  <span style={{ color: C.textDim, fontSize: 12 }}>
                    {c.episode_count || 0} episodes &middot; {c.claim_count || 0} claims
                  </span>
                </Link>
                <span style={{ color: C.textDim, fontSize: 12 }}>
                  {relativeTime(c.captured_at || c.created_at)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 3.5. Pending Routes (purple) */}
      {pendingEntityCount > 0 && (
        <div style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3 style={sectionTitle}>Pending Routes</h3>
            <QueueBadge count={pendingEntityCount} color={C.purple} />
          </div>
          <p style={{ fontSize: 13, color: C.textDim, marginBottom: 16, marginTop: 4 }}>
            Entities with claims held from routing until review is complete.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {pendingEntities.slice(0, 10).map((pe, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '8px 12px', fontSize: 13 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <StatusDot color={C.purple} />
                  <span style={{ color: C.text }}>{pe.entity_name || pe.blocked_on_entity}</span>
                  <span style={{ color: C.textDim, fontSize: 11 }}>
                    {pe.count} claim{pe.count !== 1 ? 's' : ''}{pe.conversation_ids && pe.conversation_ids.length > 0 ? ` across ${pe.conversation_ids.length} conversation${pe.conversation_ids.length !== 1 ? 's' : ''}` : ''}
                  </span>
                </div>
              </div>
            ))}
            {pendingEntityCount > 10 && (
              <div style={{ padding: '4px 12px', fontSize: 12, color: C.textDim }}>
                ...and {pendingEntityCount - 10} more
              </div>
            )}
          </div>
        </div>
      )}

      {/* 3.7. Organization Review (amber) — always visible */}
      <div style={sectionStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h3 style={sectionTitle}>Organization Review</h3>
          {provOrgs.total > 0 && <QueueBadge count={provOrgs.total} color={C.warning} />}
        </div>
        {provOrgs.total > 0 ? (
          <>
            <p style={{ fontSize: 13, color: C.textDim, marginBottom: 16, marginTop: 4 }}>
              Unresolved organization names from conversations. Create, link to existing, or dismiss.
            </p>
            <div>
              {provOrgs.groups.map(group => (
                <ProvisionalOrgCard
                  key={group.normalized_name}
                  group={group}
                  onAction={loadProvOrgs}
                />
              ))}
            </div>
          </>
        ) : (
          <div style={{
            padding: '16px 20px', borderRadius: 6,
            background: '#111827',
            border: '1px solid #1f2937',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 4 }}>
              No organizations to review
            </div>
            <div style={{ fontSize: 11, color: '#4b5563' }}>
              Organization suggestions from conversations will appear here for review when detected.
            </div>
          </div>
        )}
      </div>

      {/* 4. Processing (dim) */}
      {processing.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={sectionTitle}>Processing</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 12 }}>
            {processing.map(c => {
              const info = statusLabels[c.processing_status] || { label: c.processing_status, color: C.textDim };
              return (
                <div key={c.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px', fontSize: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <StatusDot color={info.color} />
                    <span style={{ color: C.textMuted }}>{c.manual_note || c.title || (c.source + ' capture')}</span>
                  </div>
                  <span style={{ fontSize: 12, color: info.color }}>{info.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 5. Pending (dim) */}
      {pending.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={sectionTitle}>Pending</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 12 }}>
            {pending.map(c => (
              <div key={c.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px', fontSize: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <StatusDot color={C.textDim} />
                  <span style={{ color: C.textMuted }}>{c.manual_note || c.title || (c.source + ' capture')}</span>
                </div>
                <span style={{ fontSize: 12, color: C.textDim }}>pending</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 6. Recently Reviewed (green) */}
      {recentlyReviewed.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={sectionTitle}>Recently Reviewed</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 12 }}>
            {recentlyReviewed.map(c => (
              <Link key={c.id} to={`/review/${c.id}`} style={rowStyle}
                onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ color: C.success, fontSize: 12 }}>{'✓'}</span>
                  <span style={{ color: C.textMuted, fontSize: 14 }}>
                    {c.manual_note || c.title || (c.source + " capture")}
                    {c.duration_seconds ? ` — ${Math.round(c.duration_seconds / 60)}min` : ''}
                  </span>
                  <span style={{ color: C.textDim, fontSize: 12 }}>
                    {c.episode_count || 0} ep &middot; {c.claim_count || 0} claims
                  </span>
                </div>
                <span style={{ color: C.textDim, fontSize: 12 }}>
                  reviewed {relativeTime(c.reviewed_at)}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* 7. Belief Review (teal) */}
      {beliefStats && beliefStats.total > 0 && (
        <div style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3 style={sectionTitle}>Belief Review</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              {beliefStats.by_family.under_review > 0 && <QueueBadge count={beliefStats.by_family.under_review} color={C.warning} />}
              {beliefStats.by_family.contested > 0 && <QueueBadge count={beliefStats.by_family.contested} color={C.danger} />}
            </div>
          </div>
          <p style={{ fontSize: 13, color: C.textDim, marginBottom: 16, marginTop: 4 }}>
            Beliefs that are under review, contested, or stale. Confirm, correct, or invalidate.
          </p>
          <Link to="/review/beliefs" style={{
            ...rowStyle,
            textDecoration: 'none',
          }}
            onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <StatusDot color={C.warning} />
              <span style={{ color: C.text, fontSize: 14 }}>
                {beliefStats.by_family.under_review || 0} under review
                {proposalCount > 0 && (
                  <span style={{ color: C.accent }}> ({proposalCount} with proposals)</span>
                )}
                {beliefStats.by_family.contested > 0 && ` · ${beliefStats.by_family.contested} contested`}
              </span>
            </div>
            <span style={{ color: C.accent, fontSize: 13 }}>Open Belief Review →</span>
          </Link>
        </div>
      )}

      {hasNothing && (
        <div style={{ textAlign: 'center', padding: 48, color: C.textDim }}>
          <p style={{ fontSize: 18, marginBottom: 8 }}>Nothing needs review.</p>
          <p style={{ fontSize: 14 }}>Conversations will appear here after processing.</p>
        </div>
      )}
      </>)}

      {/* Learning Health Indicator (Change 4) */}
      {learningData && (
        <div style={{
          marginTop: 24, padding: '10px 16px', borderRadius: 6,
          background: C.card, border: `1px solid ${C.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          fontSize: 12, color: C.textDim,
        }}>
          <span>
            <span style={{ color: learningData.pending_corrections >= 25 ? C.warning : C.textDim }}>
              {learningData.pending_corrections} corrections since last amendment
            </span>
            {learningData.pending_corrections >= 25 && (
              <span style={{ color: C.warning, marginLeft: 6 }}>(analysis will trigger soon)</span>
            )}
            {learningData.active_amendment && (
              <> &middot; Current: {learningData.active_amendment.version}</>
            )}
          </span>
          <Link to="/learning" style={{ color: C.accent, textDecoration: 'none', fontSize: 12 }}>
            Learning &rarr;
          </Link>
        </div>
      )}
    </div>
  );
}
