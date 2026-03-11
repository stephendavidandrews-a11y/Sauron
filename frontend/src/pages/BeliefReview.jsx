import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';

const C = {
  bg: '#0a0f1a', card: '#111827', cardHover: '#1a2234',
  border: '#1f2937', text: '#e5e7eb',
  textMuted: '#9ca3af', textDim: '#6b7280',
  accent: '#3b82f6', success: '#10b981', warning: '#f59e0b',
  danger: '#ef4444', purple: '#8b5cf6', amber: '#f59e0b',
};

const FAMILIES = {
  solid: { label: 'Solid', color: '#10b981', statuses: ['active', 'refined'] },
  shifting: { label: 'Shifting', color: '#f59e0b', statuses: ['provisional', 'qualified', 'time_bounded'] },
  contested: { label: 'Contested', color: '#ef4444', statuses: ['contested'] },
  stale: { label: 'Stale', color: '#6b7280', statuses: ['stale'] },
  under_review: { label: 'Under Review', color: '#8b5cf6', statuses: ['under_review'] },
};

function getFamily(status) {
  for (const [key, fam] of Object.entries(FAMILIES)) {
    if (fam.statuses.includes(status)) return { key, ...fam };
  }
  return { key: 'unknown', label: status, color: C.textDim, statuses: [] };
}

function StatusChip({ status }) {
  const fam = getFamily(status);
  return (
    <span style={{
      fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
      background: `${fam.color}22`, color: fam.color,
    }}>
      {fam.label}
    </span>
  );
}

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function EvidenceItem({ item }) {
  return (
    <div style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
        <span style={{
          fontSize: 10, padding: '1px 6px', borderRadius: 3, fontWeight: 500,
          background: item.evidence_role === 'support' ? `${C.success}22` :
                     item.evidence_role === 'contradiction' ? `${C.danger}22` :
                     `${C.accent}22`,
          color: item.evidence_role === 'support' ? C.success :
                 item.evidence_role === 'contradiction' ? C.danger : C.accent,
        }}>
          {item.evidence_role}
        </span>
        <span style={{ fontSize: 11, color: C.textDim }}>
          {item.claim_type} · {Math.round((item.claim_confidence || 0) * 100)}%
        </span>
      </div>
      <div style={{ fontSize: 13, color: C.text, marginBottom: 4 }}>{item.claim_text}</div>
      {item.evidence_quote && (
        <div style={{ fontSize: 12, color: C.textMuted, fontStyle: 'italic', paddingLeft: 12, borderLeft: `2px solid ${C.border}`, marginBottom: 4 }}>
          "{item.evidence_quote}"
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, fontSize: 11, color: C.textDim }}>
        {item.episode_title && <span>{item.episode_title}</span>}
        {item.conversation_source && <span>· {item.conversation_source}</span>}
        {item.conversation_date && <span>· {timeAgo(item.conversation_date)}</span>}
        {item.conversation_id && (
          <Link to={`/review/${item.conversation_id}`} style={{ color: C.accent, textDecoration: 'none' }}>View →</Link>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Re-synthesis proposal display (Feature 1)
// ---------------------------------------------------------------------------

function ResynthesisProposal({ proposal, onAccept, onReject, onEdit }) {
  const [editing, setEditing] = useState(false);
  const [editSummary, setEditSummary] = useState(proposal.proposed_summary || '');
  const [editStatus, setEditStatus] = useState(proposal.proposed_status || 'active');
  const [editConfidence, setEditConfidence] = useState(
    proposal.proposed_confidence != null ? Math.round(proposal.proposed_confidence * 100) : 50
  );
  const [saving, setSaving] = useState(false);

  const proposedFam = getFamily(proposal.proposed_status);
  const currentFam = getFamily(proposal.current_status);

  const handleAccept = async () => {
    setSaving(true);
    try { await onAccept(proposal.id); } catch (e) { console.error(e); }
    setSaving(false);
  };

  const handleReject = async () => {
    setSaving(true);
    try { await onReject(proposal.id); } catch (e) { console.error(e); }
    setSaving(false);
  };

  const handleSaveEdit = async () => {
    setSaving(true);
    try {
      await onEdit(proposal.id, editSummary, editStatus, editConfidence / 100);
    } catch (e) { console.error(e); }
    setSaving(false);
    setEditing(false);
  };

  const btnStyle = (color) => ({
    padding: '5px 12px', fontSize: 11, border: `1px solid ${color}44`,
    background: `${color}15`, color, borderRadius: 4, cursor: saving ? 'wait' : 'pointer',
    fontWeight: 500, opacity: saving ? 0.6 : 1,
  });

  const statusOptions = ['active', 'provisional', 'refined', 'qualified', 'contested', 'stale', 'superseded'];

  return (
    <div style={{
      background: `${C.purple}08`, border: `1px solid ${C.purple}33`,
      borderRadius: 6, padding: 12, marginTop: 12,
    }}>
      <div style={{
        display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8,
      }}>
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700,
          background: `${C.purple}22`, color: C.purple, textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}>
          Proposed Update
        </span>
        <span style={{ fontSize: 10, color: C.textDim }}>
          via re-synthesis · {timeAgo(proposal.created_at)}
        </span>
      </div>

      {!editing ? (
        <>
          {/* Current → Proposed diff display */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 11, color: C.textDim, marginBottom: 2 }}>Current:</div>
            <div style={{
              fontSize: 12, color: C.textMuted, padding: '4px 8px',
              background: `${C.danger}08`, borderRadius: 4, marginBottom: 6,
              textDecoration: 'line-through', opacity: 0.7,
            }}>
              {proposal.current_summary}
            </div>
            <div style={{ fontSize: 11, color: C.textDim, marginBottom: 2 }}>Proposed:</div>
            <div style={{
              fontSize: 13, color: C.text, padding: '4px 8px',
              background: `${C.success}08`, borderRadius: 4,
            }}>
              {proposal.proposed_summary}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: C.textDim }}>Status:</span>
              <StatusChip status={proposal.current_status} />
              <span style={{ color: C.textDim, fontSize: 11 }}>→</span>
              <StatusChip status={proposal.proposed_status} />
            </div>
            <div style={{ fontSize: 11, color: C.textDim }}>
              Confidence: {Math.round((proposal.proposed_confidence || 0) * 100)}%
            </div>
          </div>

          {proposal.reasoning && (
            <div style={{
              fontSize: 12, color: C.textMuted, fontStyle: 'italic',
              paddingLeft: 10, borderLeft: `2px solid ${C.purple}44`, marginBottom: 10,
            }}>
              {proposal.reasoning}
            </div>
          )}

          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={handleAccept} disabled={saving} style={btnStyle(C.success)}>
              Accept
            </button>
            <button onClick={() => setEditing(true)} disabled={saving} style={btnStyle(C.accent)}>
              Edit & Accept
            </button>
            <button onClick={handleReject} disabled={saving} style={btnStyle(C.danger)}>
              Reject
            </button>
          </div>
        </>
      ) : (
        <>
          {/* Edit mode */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 11, color: C.textDim, marginBottom: 4 }}>Summary:</div>
            <textarea
              value={editSummary}
              onChange={e => setEditSummary(e.target.value)}
              rows={3}
              style={{
                width: '100%', padding: '6px 8px', fontSize: 13, background: C.bg,
                color: C.text, border: `1px solid ${C.border}`, borderRadius: 4,
                outline: 'none', resize: 'vertical', fontFamily: 'inherit',
                boxSizing: 'border-box',
              }}
            />
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
            <div>
              <span style={{ fontSize: 11, color: C.textDim, marginRight: 4 }}>Status:</span>
              <select
                value={editStatus}
                onChange={e => setEditStatus(e.target.value)}
                style={{
                  padding: '3px 6px', fontSize: 12, background: C.bg,
                  color: C.text, border: `1px solid ${C.border}`, borderRadius: 4,
                }}
              >
                {statusOptions.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <span style={{ fontSize: 11, color: C.textDim, marginRight: 4 }}>Confidence:</span>
              <input
                type="number" min="0" max="100"
                value={editConfidence}
                onChange={e => setEditConfidence(Number(e.target.value))}
                style={{
                  width: 50, padding: '3px 6px', fontSize: 12, background: C.bg,
                  color: C.text, border: `1px solid ${C.border}`, borderRadius: 4,
                }}
              />
              <span style={{ fontSize: 11, color: C.textDim, marginLeft: 2 }}>%</span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={handleSaveEdit} disabled={saving} style={btnStyle(C.success)}>
              Save & Apply
            </button>
            <button onClick={() => setEditing(false)} disabled={saving} style={btnStyle(C.textDim)}>
              Cancel
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function BeliefActions({ belief, transitions, onAction }) {
  const [feedback, setFeedback] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);
  const st = belief.status;
  const act = (newStatus) => {
    onAction(belief.id, newStatus, feedback || null);
    setShowFeedback(false);
    setFeedback('');
  };
  const getPreviousStatus = () => {
    if (transitions && transitions.length > 0) {
      const urTransition = transitions.find(t => t.new_status === 'under_review');
      if (urTransition && urTransition.old_status) return urTransition.old_status;
    }
    return 'active';
  };
  const btnStyle = (color) => ({
    padding: '4px 10px', fontSize: 11, border: `1px solid ${color}44`,
    background: `${color}15`, color, borderRadius: 4, cursor: 'pointer', fontWeight: 500,
  });

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {st === 'under_review' && (<>
          <button onClick={() => act(getPreviousStatus())} style={btnStyle(C.success)}>Still Valid</button>
          <button onClick={() => setShowFeedback(!showFeedback)} style={btnStyle(C.accent)}>Needs Rewording</button>
          <button onClick={() => act('stale')} style={btnStyle(C.textDim)}>No Longer Holds</button>
          <button onClick={() => act('contested')} style={btnStyle(C.danger)}>Evidence Conflicts</button>
          <button onClick={() => act('superseded')} style={btnStyle(C.danger)}>Dismiss</button>
        </>)}
        {st === 'contested' && (<>
          <button onClick={() => act('active')} style={btnStyle(C.success)}>Resolve Active</button>
          <button onClick={() => act('qualified')} style={btnStyle(C.warning)}>Resolve Qualified</button>
          <button onClick={() => act('stale')} style={btnStyle(C.textDim)}>Mark Stale</button>
          <button onClick={() => act('superseded')} style={btnStyle(C.danger)}>Dismiss</button>
        </>)}
        {st === 'provisional' && (<>
          <button onClick={() => act('active')} style={btnStyle(C.success)}>Confirm Active</button>
          <button onClick={() => act('qualified')} style={btnStyle(C.warning)}>Qualify</button>
          <button onClick={() => act('contested')} style={btnStyle(C.danger)}>Contest</button>
          <button onClick={() => act('superseded')} style={btnStyle(C.danger)}>Dismiss</button>
        </>)}
        {(st === 'active' || st === 'refined') && (<>
          <button onClick={() => act('qualified')} style={btnStyle(C.warning)}>Qualify</button>
          <button onClick={() => act('contested')} style={btnStyle(C.danger)}>Contest</button>
          <button onClick={() => act('stale')} style={btnStyle(C.textDim)}>Mark Stale</button>
          <button onClick={() => act('superseded')} style={btnStyle(C.danger)}>Dismiss</button>
        </>)}
        {st === 'stale' && (<>
          <button onClick={() => act('active')} style={btnStyle(C.success)}>Reconfirm</button>
          <button onClick={() => act('superseded')} style={btnStyle(C.danger)}>Dismiss</button>
        </>)}
        {(st === 'qualified' || st === 'time_bounded') && (<>
          <button onClick={() => act('active')} style={btnStyle(C.success)}>Confirm Active</button>
          <button onClick={() => act('contested')} style={btnStyle(C.danger)}>Contest</button>
          <button onClick={() => act('superseded')} style={btnStyle(C.danger)}>Dismiss</button>
        </>)}
      </div>
      {showFeedback && (
        <div style={{ marginTop: 8, display: 'flex', gap: 6 }}>
          <input type="text" placeholder="Updated wording..."
            value={feedback} onChange={e => setFeedback(e.target.value)}
            style={{ flex: 1, padding: '6px 8px', fontSize: 12, background: C.bg, color: C.text,
              border: `1px solid ${C.border}`, borderRadius: 4, outline: 'none' }} />
          <button onClick={() => act('refined')} style={btnStyle(C.accent)}>Save</button>
        </div>
      )}
    </div>
  );
}

function BeliefCard({ belief, onAction, proposal, onAcceptProposal, onRejectProposal, onEditProposal }) {
  const [expanded, setExpanded] = useState(false);
  const [evidence, setEvidence] = useState(null);
  const [transitions, setTransitions] = useState(null);
  const [loading, setLoading] = useState(false);
  const handleExpand = async () => {
    if (expanded) { setExpanded(false); return; }
    setExpanded(true);
    if (!evidence) {
      setLoading(true);
      try {
        const [evData, trData] = await Promise.all([
          api.beliefEvidence(belief.id),
          api.beliefTransitions(belief.id),
        ]);
        setEvidence(evData?.evidence || []);
        setTransitions(trData || []);
      } catch (e) { console.error('Failed to load belief details:', e); }
      setLoading(false);
    }
  };
  const fam = getFamily(belief.status);
  const roleOrder = ['support', 'contradiction', 'refinement', 'qualification'];
  const groupedEvidence = evidence ? roleOrder
    .map(role => ({ role, items: evidence.filter(e => e.evidence_role === role) }))
    .filter(g => g.items.length > 0) : [];

  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
      padding: 16, marginBottom: 8, borderLeft: `3px solid ${fam.color}`,
    }}>
      <div onClick={handleExpand} style={{ cursor: 'pointer' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, color: C.text, lineHeight: 1.5, marginBottom: 6 }}>
              {belief.belief_summary}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <StatusChip status={belief.status} />
              <span style={{ fontSize: 11, color: C.textDim }}>
                {Math.round((belief.confidence || 0) * 100)}% confidence
              </span>
              {belief.entity_name && (
                <span style={{ fontSize: 11, color: C.textMuted }}>· {belief.entity_name}</span>
              )}
              {!belief.entity_name && belief.entity_type && (
                <span style={{ fontSize: 11, color: C.textMuted }}>· {belief.entity_type}</span>
              )}
              <span style={{ fontSize: 11, color: C.textDim }}>
                · {belief.support_count || 0}↑ {belief.contradiction_count || 0}↓
              </span>
              {belief.last_confirmed_at && (
                <span style={{ fontSize: 11, color: C.textDim }}>· confirmed {timeAgo(belief.last_confirmed_at)}</span>
              )}
              {proposal && (
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 3, fontWeight: 600,
                  background: `${C.purple}22`, color: C.purple,
                }}>
                  Proposal available
                </span>
              )}
            </div>
          </div>
          <span style={{ color: C.textDim, fontSize: 12, flexShrink: 0 }}>
            {expanded ? '▼' : '▶'}
          </span>
        </div>
      </div>
      {expanded && (
        <div style={{ marginTop: 16, borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
          {loading && (<div style={{ color: C.textDim, fontSize: 12, padding: 8 }}>Loading evidence...</div>)}

          {/* Re-synthesis proposal (Feature 1) */}
          {proposal && (
            <ResynthesisProposal
              proposal={proposal}
              onAccept={onAcceptProposal}
              onReject={onRejectProposal}
              onEdit={onEditProposal}
            />
          )}

          {transitions && transitions.length > 0 && (
            <div style={{ marginBottom: 12, marginTop: proposal ? 12 : 0 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
                Movement History
              </div>
              {transitions.slice(0, 5).map((t, i) => (
                <div key={t.id || i} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '3px 0', fontSize: 12 }}>
                  <span style={{ color: C.textDim }}>{t.old_status || '(new)'}</span>
                  <span style={{ color: C.textMuted }}>→</span>
                  <StatusChip status={t.new_status} />
                  <span style={{
                    fontSize: 10, padding: '1px 5px', borderRadius: 3,
                    background: t.driver === 'new_evidence' ? `${C.accent}22` :
                               t.driver === 'correction' ? `${C.warning}22` :
                               t.driver === 'resynthesis' ? `${C.purple}22` : `${C.purple}22`,
                    color: t.driver === 'new_evidence' ? C.accent :
                           t.driver === 'correction' ? C.warning :
                           t.driver === 'resynthesis' ? C.purple : C.purple,
                  }}>
                    {t.driver?.replace('_', ' ')}
                  </span>
                  {t.cause_summary && <span style={{ fontSize: 11, color: C.textDim }}>{t.cause_summary}</span>}
                  <span style={{ fontSize: 10, color: C.textDim, marginLeft: 'auto' }}>{timeAgo(t.created_at)}</span>
                </div>
              ))}
            </div>
          )}
          {groupedEvidence.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
                Evidence ({evidence.length})
              </div>
              {groupedEvidence.map(group => (
                <div key={group.role}>
                  {groupedEvidence.length > 1 && (
                    <div style={{ fontSize: 11, color: C.textDim, fontWeight: 600, marginTop: 8, marginBottom: 4 }}>
                      {group.role.charAt(0).toUpperCase() + group.role.slice(1)} ({group.items.length})
                    </div>
                  )}
                  {group.items.map((item, i) => (<EvidenceItem key={item.evidence_id || i} item={item} />))}
                </div>
              ))}
            </div>
          )}
          {!loading && evidence && evidence.length === 0 && (
            <div style={{ fontSize: 12, color: C.textDim, padding: 8 }}>No evidence linked to this belief.</div>
          )}
          {proposal && (
            <div style={{ textAlign: 'center', margin: '8px 0', fontSize: 11, color: C.textDim }}>
              — or handle manually —
            </div>
          )}
          <BeliefActions belief={belief} transitions={transitions} onAction={onAction} />
        </div>
      )}
    </div>
  );
}

function TransitionCard({ transition, onAction, proposal, onAcceptProposal, onRejectProposal, onEditProposal }) {
  const belief = {
    id: transition.belief_id,
    belief_summary: transition.belief_summary,
    status: transition.current_status,
    confidence: transition.confidence,
    entity_name: transition.entity_name,
    entity_type: transition.entity_type,
    support_count: transition.support_count,
    contradiction_count: transition.contradiction_count,
  };
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4, paddingLeft: 4 }}>
        <span style={{ fontSize: 11, color: C.textDim }}>{transition.old_status || '(new)'}</span>
        <span style={{ color: C.textMuted, fontSize: 11 }}>→</span>
        <StatusChip status={transition.new_status} />
        <span style={{
          fontSize: 10, padding: '1px 5px', borderRadius: 3,
          background: transition.driver === 'new_evidence' ? `${C.accent}22` :
                     transition.driver === 'correction' ? `${C.warning}22` :
                     transition.driver === 'resynthesis' ? `${C.purple}22` : `${C.purple}22`,
          color: transition.driver === 'new_evidence' ? C.accent :
                 transition.driver === 'correction' ? C.warning :
                 transition.driver === 'resynthesis' ? C.purple : C.purple,
        }}>
          {transition.driver?.replace('_', ' ')}
        </span>
        {transition.cause_summary && (
          <span style={{ fontSize: 11, color: C.textDim }}>{transition.cause_summary}</span>
        )}
        <span style={{ fontSize: 10, color: C.textDim, marginLeft: 'auto' }}>{timeAgo(transition.created_at)}</span>
      </div>
      <BeliefCard
        belief={belief}
        onAction={onAction}
        proposal={proposal}
        onAcceptProposal={onAcceptProposal}
        onRejectProposal={onRejectProposal}
        onEditProposal={onEditProposal}
      />
    </div>
  );
}

export default function BeliefReview() {
  const [mode, setMode] = useState('attention');
  const [beliefs, setBeliefs] = useState([]);
  const [transitions, setTransitions] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [familyFilter, setFamilyFilter] = useState(null);
  const [proposals, setProposals] = useState([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const statsData = await api.beliefStats();
      setStats(statsData);

      // Load pending resynthesis proposals
      try {
        const proposalData = await api.pendingResyntheses();
        setProposals(proposalData || []);
      } catch (e) {
        console.error('Failed to load resynthesis proposals:', e);
        setProposals([]);
      }

      if (mode === 'attention') {
        const [ur, cont, staleData] = await Promise.all([
          api.beliefs({ limit: 50, status: 'under_review' }),
          api.beliefs({ limit: 50, status: 'contested' }),
          api.beliefs({ limit: 50, status: 'stale' }),
        ]);
        let merged = [
          ...(ur || []).map(b => ({ ...b, _priority: 0 })),
          ...(cont || []).map(b => ({ ...b, _priority: 1 })),
          ...(staleData || []).map(b => ({ ...b, _priority: 2 })),
        ];
        const seen = new Set();
        merged = merged.filter(b => {
          if (seen.has(b.id)) return false;
          seen.add(b.id);
          return true;
        });
        merged.sort((a, b) => a._priority - b._priority);
        setBeliefs(merged);
      } else {
        const trData = await api.recentTransitions(14, 100);
        setTransitions(trData || []);
      }
    } catch (e) { console.error('Failed to load belief data:', e); }
    setLoading(false);
  }, [mode]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleAction = async (beliefId, newStatus, feedback) => {
    try {
      await api.correctBelief(beliefId, newStatus, feedback);
      setBeliefs(prev => prev.map(b => b.id === beliefId ? { ...b, status: newStatus } : b));
      // Also remove any proposal for this belief
      setProposals(prev => prev.filter(p => p.belief_id !== beliefId));
      api.beliefStats().then(setStats).catch(() => {});
    } catch (e) { console.error('Failed to update belief:', e); }
  };

  // Proposal action handlers
  const getProposalForBelief = (beliefId) => proposals.find(p => p.belief_id === beliefId);

  const handleAcceptProposal = async (proposalId) => {
    try {
      const result = await api.acceptResynthesis(proposalId);
      // Update local state
      const proposal = proposals.find(p => p.id === proposalId);
      if (proposal) {
        setBeliefs(prev => prev.map(b =>
          b.id === proposal.belief_id
            ? { ...b, status: proposal.proposed_status, belief_summary: proposal.proposed_summary, confidence: proposal.proposed_confidence }
            : b
        ));
      }
      setProposals(prev => prev.filter(p => p.id !== proposalId));
      api.beliefStats().then(setStats).catch(() => {});
    } catch (e) { console.error('Failed to accept proposal:', e); }
  };

  const handleRejectProposal = async (proposalId) => {
    try {
      await api.rejectResynthesis(proposalId);
      setProposals(prev => prev.filter(p => p.id !== proposalId));
    } catch (e) { console.error('Failed to reject proposal:', e); }
  };

  const handleEditProposal = async (proposalId, summary, status, confidence) => {
    try {
      await api.editResynthesis(proposalId, summary, status, confidence);
      const proposal = proposals.find(p => p.id === proposalId);
      if (proposal) {
        setBeliefs(prev => prev.map(b =>
          b.id === proposal.belief_id
            ? { ...b, status, belief_summary: summary, confidence }
            : b
        ));
      }
      setProposals(prev => prev.filter(p => p.id !== proposalId));
      api.beliefStats().then(setStats).catch(() => {});
    } catch (e) { console.error('Failed to edit proposal:', e); }
  };

  const filteredBeliefs = familyFilter
    ? beliefs.filter(b => FAMILIES[familyFilter]?.statuses.includes(b.status))
    : beliefs;
  const filteredTransitions = familyFilter
    ? transitions.filter(t => FAMILIES[familyFilter]?.statuses.includes(t.current_status))
    : transitions;
  const attentionCount = (stats?.by_family?.under_review || 0) + (stats?.by_family?.contested || 0) + (stats?.by_family?.stale || 0);
  const proposalCount = proposals.length;

  // Compute pill counts from loaded data, not global stats
  const pillCounts = mode === 'movement'
    ? (() => { const c = {}; for (const [k, f] of Object.entries(FAMILIES)) c[k] = transitions.filter(t => f.statuses.includes(t.current_status)).length; return c; })()
    : (() => { const c = {}; for (const [k, f] of Object.entries(FAMILIES)) c[k] = beliefs.filter(b => f.statuses.includes(b.status)).length; return c; })();

  return (
    <div style={{ padding: '24px 0' }}>
      <Link to="/review" style={{ color: C.accent, fontSize: 13, textDecoration: 'none' }}>&larr; Back to Review</Link>
      <div style={{ marginTop: 16, marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: C.text, margin: 0 }}>Belief Review</h1>
        <p style={{ fontSize: 13, color: C.textDim, marginTop: 4 }}>
          {stats ? `${stats.total} beliefs · ${attentionCount} need attention` : 'Loading...'}
          {proposalCount > 0 && (
            <span style={{ color: C.purple, fontWeight: 600 }}>
              {' '}· {proposalCount} re-synthesis proposal{proposalCount !== 1 ? 's' : ''}
            </span>
          )}
        </p>
      </div>

      <div style={{ display: 'flex', gap: 0, marginBottom: 16 }}>
        {[
          { key: 'attention', label: 'Needs Attention', count: attentionCount },
          { key: 'movement', label: 'Recent Movement', count: transitions.length || null },
        ].map(tab => (
          <button key={tab.key}
            onClick={() => { setMode(tab.key); setFamilyFilter(null); }}
            style={{
              padding: '8px 16px', fontSize: 13, fontWeight: mode === tab.key ? 600 : 400,
              background: mode === tab.key ? C.card : 'transparent',
              color: mode === tab.key ? C.text : C.textDim,
              border: `1px solid ${mode === tab.key ? C.border : 'transparent'}`,
              borderBottom: mode === tab.key ? 'none' : `1px solid ${C.border}`,
              borderRadius: mode === tab.key ? '6px 6px 0 0' : 0,
              cursor: 'pointer',
            }}
          >
            {tab.label}
            {tab.count > 0 && (
              <span style={{
                marginLeft: 6, fontSize: 10, padding: '1px 5px', borderRadius: 8,
                background: `${C.accent}33`, color: C.accent, fontWeight: 700,
              }}>{tab.count}</span>
            )}
          </button>
        ))}
      </div>

      {stats && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
          <button onClick={() => setFamilyFilter(null)}
            style={{
              padding: '3px 10px', fontSize: 11, borderRadius: 12, cursor: 'pointer',
              background: !familyFilter ? C.accent : 'transparent',
              color: !familyFilter ? '#fff' : C.textDim,
              border: `1px solid ${!familyFilter ? C.accent : C.border}`,
            }}
          >All</button>
          {Object.entries(FAMILIES)
            .map(([key, fam]) => {
            const count = pillCounts[key] || 0;
            const isEmpty = count === 0;
            return (
              <button key={key}
                onClick={isEmpty ? undefined : () => setFamilyFilter(familyFilter === key ? null : key)}
                style={{
                  padding: '3px 10px', fontSize: 11, borderRadius: 12,
                  cursor: isEmpty ? 'default' : 'pointer',
                  opacity: isEmpty ? 0.35 : 1,
                  background: familyFilter === key && !isEmpty ? `${fam.color}33` : 'transparent',
                  color: familyFilter === key && !isEmpty ? fam.color : C.textDim,
                  border: `1px solid ${familyFilter === key && !isEmpty ? fam.color : C.border}`,
                }}
              >{fam.label} ({count})</button>
            );
          })}
        </div>
      )}

      {loading && (
        <div style={{ padding: 48, textAlign: 'center', color: C.textDim }}>Loading beliefs...</div>
      )}

      {!loading && mode === 'attention' && (
        <>
          {filteredBeliefs.length === 0 ? (
            <div style={{
              background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
              padding: 32, textAlign: 'center',
            }}>
              <div style={{ fontSize: 14, color: C.textMuted, marginBottom: 4 }}>
                {familyFilter ? 'No beliefs match this filter.' : 'All beliefs are in good standing.'}
              </div>
              <div style={{ fontSize: 12, color: C.textDim }}>
                Beliefs move here when evidence is corrected, conflicts arise, or they go stale.
              </div>
            </div>
          ) : (
            filteredBeliefs.map(b => (
              <BeliefCard
                key={b.id}
                belief={b}
                onAction={handleAction}
                proposal={getProposalForBelief(b.id)}
                onAcceptProposal={handleAcceptProposal}
                onRejectProposal={handleRejectProposal}
                onEditProposal={handleEditProposal}
              />
            ))
          )}
        </>
      )}

      {!loading && mode === 'movement' && (
        <>
          {filteredTransitions.length === 0 ? (
            <div style={{
              background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
              padding: 32, textAlign: 'center',
            }}>
              <div style={{ fontSize: 14, color: C.textMuted, marginBottom: 4 }}>
                No belief transitions in the last 14 days.
              </div>
              <div style={{ fontSize: 12, color: C.textDim }}>
                Transitions appear when the pipeline updates beliefs or you take review actions.
              </div>
            </div>
          ) : (
            filteredTransitions.map((t, i) => (
              <TransitionCard
                key={t.id || i}
                transition={t}
                onAction={handleAction}
                proposal={getProposalForBelief(t.belief_id)}
                onAcceptProposal={handleAcceptProposal}
                onRejectProposal={handleRejectProposal}
                onEditProposal={handleEditProposal}
              />
            ))
          )}
        </>
      )}
    </div>
  );
}
