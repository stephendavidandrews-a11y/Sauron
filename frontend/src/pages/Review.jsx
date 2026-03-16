import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { fetchPendingRoutes, fetchProvisionalOrgs, approveProvisionalOrg, mergeProvisionalOrg, dismissProvisionalOrg, searchNetworkingOrgs } from '../api';

export const C = {
  bg: '#0a0f1a', card: '#111827', cardHover: '#1a2234',
  border: '#1f2937', text: '#e5e7eb',
  textMuted: '#9ca3af', textDim: '#6b7280',
  accent: '#3b82f6', success: '#10b981', warning: '#f59e0b',
  danger: '#ef4444', purple: '#a78bfa', amber: '#f59e0b',
};

function relativeTime(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffDays = Math.floor(diffMs / 86400000);
  const diffHours = Math.floor(diffMs / 3600000);
  if (diffHours < 1) return 'just now';
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;
  return date.toLocaleDateString();
}

function StatusDot({ color }) {
  return <span style={{ color, fontSize: 10 }}>{'\u25CF'}</span>;
}

function QueueBadge({ count, color }) {
  if (!count) return null;
  return (
    <span style={{
      fontSize: 12, padding: '2px 8px', borderRadius: 10,
      background: color + '33', color, fontWeight: 600,
    }}>{count}</span>
  );
}

// ═══════════════════════════════════════════════════════
// QUICK PASS — compact error type picker for dismiss
// ═══════════════════════════════════════════════════════

export const DISMISS_REASONS = [
  { key: 'hallucinated_claim', label: 'Hallucinated', shortcut: '1' },
  { key: 'overstated_position', label: 'Overstated', shortcut: '2' },
  { key: 'wrong_claim_type', label: 'Wrong type', shortcut: '3' },
  { key: 'bad_entity_linking', label: 'Bad entity', shortcut: '4' },
  { key: 'bad_commitment_extraction', label: 'Bad extraction', shortcut: '5' },
];

export function QuickPassErrorPicker({ onSelect, onCancel }) {
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') { onCancel(); return; }
      const reason = DISMISS_REASONS.find(r => r.shortcut === e.key);
      if (reason) onSelect(reason.key);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onSelect, onCancel]);

  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
      {DISMISS_REASONS.map(r => (
        <button key={r.key} onClick={() => onSelect(r.key)}
          style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3,
            border: `1px solid ${C.danger}40`, background: 'transparent',
            color: C.danger, cursor: 'pointer' }}>
          <span style={{ opacity: 0.5, marginRight: 3 }}>{r.shortcut}</span>{r.label}
        </button>
      ))}
      <button onClick={onCancel}
        style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3,
          border: `1px solid ${C.border}`, background: 'transparent',
          color: C.textDim, cursor: 'pointer' }}>Esc</button>
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// QUICK PASS — claim card for rapid triage
// ═══════════════════════════════════════════════════════

export const claimTypeColors = {
  fact: '#3b82f6', position: '#8b5cf6', commitment: '#f59e0b',
  preference: '#10b981', relationship: '#ec4899', observation: '#6366f1',
  tactical: '#ef4444',
};

export function QuickPassClaimCard({ claim, isFocused, onApprove, onDismiss, onEdit, onFlag, isEditing,
  editText, onEditChange, onEditSave, onEditCancel }) {
  const [showDismiss, setShowDismiss] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const cardRef = useRef(null);

  useEffect(() => {
    if (isFocused && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [isFocused]);

  return (
    <div ref={cardRef} style={{
      padding: '10px 14px', borderRadius: 6,
      border: `1px solid ${isFocused ? C.accent : C.border}`,
      background: isFocused ? C.accent + '08' : 'transparent',
      opacity: isFocused ? 1 : 0.7,
      marginBottom: 6, transition: 'all 0.15s',
    }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, fontWeight: 600,
          background: `${claimTypeColors[claim.claim_type] || C.textDim}22`,
          color: claimTypeColors[claim.claim_type] || C.textDim, textTransform: 'uppercase' }}>
          {claim.claim_type}
        </span>
        {claim.confidence != null && (
          <span style={{ fontSize: 11, color: C.textDim }}>{(claim.confidence * 100).toFixed(0)}%</span>
        )}
        {claim.subject_name && (
          <span style={{ fontSize: 11, color: C.purple }}>{claim.subject_name}</span>
        )}
        {claim.episode_title && (
          <span style={{ fontSize: 10, color: C.textDim, fontStyle: 'italic' }}>
            {claim.episode_title}
          </span>
        )}
      </div>

      {isEditing ? (
        <div style={{ marginBottom: 6 }}>
          <textarea value={editText} onChange={e => onEditChange(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onEditSave(); }
              if (e.key === 'Escape') onEditCancel();
            }}
            autoFocus
            style={{ width: '100%', fontSize: 13, color: C.text, background: C.card,
              border: `1px solid ${C.accent}`, borderRadius: 4, padding: '6px 8px',
              resize: 'vertical', minHeight: 50 }} />
          <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
            <button onClick={onEditSave}
              style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, border: 'none',
                background: C.accent, color: '#fff', cursor: 'pointer' }}>Save (Enter)</button>
            <button onClick={onEditCancel}
              style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, border: `1px solid ${C.border}`,
                background: 'transparent', color: C.textDim, cursor: 'pointer' }}>Cancel (Esc)</button>
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 13, color: C.text, marginBottom: 4, lineHeight: 1.4 }}>
          {claim.claim_text}
        </div>
      )}

      {claim.evidence_quote && (
        <div>
          <button onClick={() => setShowEvidence(!showEvidence)}
            style={{ fontSize: 10, color: C.textDim, background: 'none', border: 'none',
              cursor: 'pointer', padding: 0 }}>
            {showEvidence ? '\u25BC' : '\u25B6'} evidence
          </button>
          {showEvidence && (
            <div style={{ fontSize: 11, color: C.textDim, fontStyle: 'italic', marginTop: 2,
              paddingLeft: 8, borderLeft: `2px solid ${C.border}` }}>
              "{claim.evidence_quote}"
            </div>
          )}
        </div>
      )}

      {claim.claim_type === 'commitment' && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
          {claim.firmness && <span style={{ fontSize: 10, color: C.warning }}>{claim.firmness}</span>}
          {claim.direction && <span style={{ fontSize: 10, color: C.textDim }}>{claim.direction}</span>}
          {claim.has_deadline && <span style={{ fontSize: 10, color: C.success }}>[deadline]</span>}
          {claim.has_condition && <span style={{ fontSize: 10, color: C.purple }}>[condition]</span>}
        </div>
      )}

      {isFocused && !isEditing && (
        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
          <button onClick={onApprove}
            style={{ fontSize: 11, padding: '3px 10px', borderRadius: 3, border: `1px solid ${C.success}44`,
              background: 'transparent', color: C.success, cursor: 'pointer' }}>
            <span style={{ opacity: 0.5, marginRight: 3 }}>a</span>{'✓'} Approve
          </button>
          <button onClick={() => setShowDismiss(true)}
            style={{ fontSize: 11, padding: '3px 10px', borderRadius: 3, border: `1px solid ${C.danger}44`,
              background: showDismiss ? C.danger + '10' : 'transparent', color: C.danger, cursor: 'pointer' }}>
            <span style={{ opacity: 0.5, marginRight: 3 }}>d</span>{'✗'} Dismiss
          </button>
          <button onClick={onFlag}
            style={{ fontSize: 11, padding: '3px 10px', borderRadius: 3, border: `1px solid ${C.warning}44`,
              background: 'transparent', color: C.warning, cursor: 'pointer' }}>
            <span style={{ opacity: 0.5, marginRight: 3 }}>f</span>{'\u2691'} Flag
          </button>
          <button onClick={onEdit}
            style={{ fontSize: 11, padding: '3px 10px', borderRadius: 3, border: `1px solid ${C.border}`,
              background: 'transparent', color: C.textDim, cursor: 'pointer' }}>
            <span style={{ opacity: 0.5, marginRight: 3 }}>e</span>{'\u270E'} Edit
          </button>
        </div>
      )}

      {showDismiss && (
        <QuickPassErrorPicker
          onSelect={(errorType) => { onDismiss(errorType); setShowDismiss(false); }}
          onCancel={() => setShowDismiss(false)} />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// QUICK PASS — main view component
// ═══════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════
// QUICK PASS — proposal card for belief resynthesis
// ═══════════════════════════════════════════════════════

export function QuickPassProposalCard({ proposal, isFocused, onAccept, onReject }) {
  const cardRef = useRef(null);

  useEffect(() => {
    if (isFocused && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [isFocused]);

  return (
    <div ref={cardRef} style={{
      padding: '10px 14px', borderRadius: 6,
      border: `1px solid ${isFocused ? '#3b82f6' : '#3b82f644'}`,
      background: isFocused ? '#3b82f610' : '#3b82f608',
      opacity: isFocused ? 1 : 0.7,
      marginBottom: 6, transition: 'all 0.15s',
    }}>
      <div style={{ fontSize: 10, color: C.accent, fontWeight: 600, textTransform: 'uppercase',
        letterSpacing: '0.05em', marginBottom: 6 }}>
        {'\u{1F504}'} BELIEF UPDATE
      </div>
      <div style={{ fontSize: 13, color: C.text, fontWeight: 600, marginBottom: 4 }}>
        {proposal.entity_name || 'Unknown'}: {proposal.belief_key || ''}
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontSize: 11, padding: '2px 6px', borderRadius: 3,
          background: C.warning + '22', color: C.warning }}>{proposal.current_status}</span>
        <span style={{ color: C.textDim, fontSize: 11 }}>\u2192</span>
        <span style={{ fontSize: 11, padding: '2px 6px', borderRadius: 3,
          background: C.accent + '22', color: C.accent }}>{proposal.proposed_status}</span>
      </div>
      <div style={{ fontSize: 13, color: C.text, marginBottom: 4, lineHeight: 1.4 }}>
        {proposal.proposed_summary}
      </div>
      {proposal.reasoning && (
        <div style={{ fontSize: 11, color: C.textDim, fontStyle: 'italic', marginBottom: 6 }}>
          {proposal.reasoning}
        </div>
      )}
      {isFocused && (
        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
          <button onClick={onAccept}
            style={{ fontSize: 11, padding: '3px 10px', borderRadius: 3, border: `1px solid ${C.success}44`,
              background: 'transparent', color: C.success, cursor: 'pointer' }}>
            <span style={{ opacity: 0.5, marginRight: 3 }}>a</span>{'\u2713'} Accept
          </button>
          <button onClick={onReject}
            style={{ fontSize: 11, padding: '3px 10px', borderRadius: 3, border: `1px solid ${C.danger}44`,
              background: 'transparent', color: C.danger, cursor: 'pointer' }}>
            <span style={{ opacity: 0.5, marginRight: 3 }}>d</span>{'\u2717'} Reject
          </button>
        </div>
      )}
    </div>
  );
}

function QuickPassView({ onExit, onMarkReviewed }) {
  const [claims, setClaims] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [focusIdx, setFocusIdx] = useState(0);
  const [editingIdx, setEditingIdx] = useState(null);
  const [editText, setEditText] = useState('');
  const [showDismissPicker, setShowDismissPicker] = useState(false);
  const [triaged, setTriaged] = useState(new Set()); // claim IDs that have been actioned
  const [flaggedConvos, setFlaggedConvos] = useState(new Set());

  const loadClaims = useCallback(async () => {
    setLoading(true);
    try {
      const [claimsData, proposalsData] = await Promise.all([
        api.unreviewedClaims(100),
        api.pendingResyntheses().catch(() => []),
      ]);
      setClaims(claimsData || []);
      setProposals(proposalsData || []);
    } catch (e) { console.error('Failed to load unreviewed claims', e); }
    setLoading(false);
  }, []);

  useEffect(() => { loadClaims(); }, [loadClaims]);

  // Filter out triaged claims and flagged conversation claims
  const activeClaims = claims.filter(c =>
    !triaged.has(c.id) && !flaggedConvos.has(c.conversation_id)
  );

  // Filter active proposals
  const activeProposals = proposals.filter(p => !triaged.has('proposal_' + p.id));

  // Group by conversation
  const convGroups = [];
  const seen = new Set();
  for (const claim of activeClaims) {
    if (!seen.has(claim.conversation_id)) {
      seen.add(claim.conversation_id);
      convGroups.push({
        convId: claim.conversation_id,
        title: claim.conv_manual_note || claim.conv_title || (claim.conv_source + ' capture'),
        captured_at: claim.conv_captured_at,
        claims: activeClaims.filter(c => c.conversation_id === claim.conversation_id),
      });
    }
  }

  // Flat list for focus navigation
  // Merged items: proposals first (faster to process), then claims
  const proposalItems = activeProposals.map(p => ({ type: 'proposal', ...p }));
  const claimItems = convGroups.flatMap(g => g.claims.map(c => ({ type: 'claim', ...c })));
  const flatClaims = [...proposalItems, ...claimItems];
  const currentClaim = flatClaims[focusIdx];

  // Check if all claims in a conversation are triaged
  const getConvTriageStatus = (convId) => {
    const convClaims = claims.filter(c => c.conversation_id === convId);
    return convClaims.every(c => triaged.has(c.id));
  };

  // Handlers
  const handleApprove = async (claimId, convId) => {
    setTriaged(prev => new Set(prev).add(claimId));
    try {
      await api.approveClaim(convId, claimId);
    } catch (e) {
      console.error('Approve failed', e);
      setTriaged(prev => { const s = new Set(prev); s.delete(claimId); return s; });
    }
  };

  const handleDismiss = async (claimId, convId, errorType) => {
    setTriaged(prev => new Set(prev).add(claimId));
    try {
      await api.dismissClaim(convId, claimId, errorType);
    } catch (e) {
      console.error('Dismiss failed', e);
      setTriaged(prev => { const s = new Set(prev); s.delete(claimId); return s; });
    }
  };

  const handleAcceptProposal = async (proposalId) => {
    setTriaged(prev => new Set(prev).add('proposal_' + proposalId));
    try {
      await api.acceptResynthesis(proposalId);
    } catch (e) {
      console.error('Accept proposal failed', e);
      setTriaged(prev => { const s = new Set(prev); s.delete('proposal_' + proposalId); return s; });
    }
  };

  const handleRejectProposal = async (proposalId) => {
    setTriaged(prev => new Set(prev).add('proposal_' + proposalId));
    try {
      await api.rejectResynthesis(proposalId);
    } catch (e) {
      console.error('Reject proposal failed', e);
      setTriaged(prev => { const s = new Set(prev); s.delete('proposal_' + proposalId); return s; });
    }
  };

  const handleFlag = async (convId) => {
    setFlaggedConvos(prev => new Set(prev).add(convId));
    try {
      await api.flagConversation(convId);
    } catch (e) {
      console.error('Flag failed', e);
      setFlaggedConvos(prev => { const s = new Set(prev); s.delete(convId); return s; });
    }
  };

  const handleEditSave = async () => {
    if (editingIdx === null) return;
    const claim = flatClaims[editingIdx];
    if (!claim || editText === claim.claim_text) { setEditingIdx(null); return; }
    // Optimistic update
    setClaims(prev => prev.map(c =>
      c.id === claim.id ? { ...c, claim_text: editText } : c
    ));
    setEditingIdx(null);
    try {
      await api.correctClaim(claim.conversation_id, claim.id, 'claim_text_edited',
        claim.claim_text, editText, null);
    } catch (e) {
      console.error('Edit failed', e);
      setClaims(prev => prev.map(c =>
        c.id === claim.id ? { ...c, claim_text: claim.claim_text } : c
      ));
    }
  };

  const handleMarkReviewed = async (convId) => {
    try {
      await api.markReviewed(convId);
      // Remove all claims for this conversation
      setClaims(prev => prev.filter(c => c.conversation_id !== convId));
      onMarkReviewed();
    } catch (e) { console.error('Mark reviewed failed', e); }
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      // Skip if in input/textarea
      const tag = document.activeElement?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

      const claim = flatClaims[focusIdx];
      if (!claim && !['Escape'].includes(e.key)) return;

      switch (e.key) {
        case 'j':
        case 'ArrowDown':
          e.preventDefault();
          setFocusIdx(prev => Math.min(prev + 1, flatClaims.length - 1));
          setShowDismissPicker(false);
          break;
        case 'k':
        case 'ArrowUp':
          e.preventDefault();
          setFocusIdx(prev => Math.max(prev - 1, 0));
          setShowDismissPicker(false);
          break;
        case 'a':
          e.preventDefault();
          if (claim) {
            if (claim.type === 'proposal') handleAcceptProposal(claim.id);
            else handleApprove(claim.id, claim.conversation_id);
          }
          break;
        case 'd':
          e.preventDefault();
          if (claim && claim.type === 'proposal') handleRejectProposal(claim.id);
          else setShowDismissPicker(true);
          break;
        case 'f':
          e.preventDefault();
          if (claim && claim.type !== 'proposal') handleFlag(claim.conversation_id);
          break;
        case 'e':
          e.preventDefault();
          if (claim && claim.type !== 'proposal') {
            setEditingIdx(focusIdx);
            setEditText(claim.claim_text);
          }
          break;
        case 'Escape':
          if (showDismissPicker) setShowDismissPicker(false);
          else onExit();
          break;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [focusIdx, flatClaims, showDismissPicker]);

  if (loading) {
    return <div style={{ padding: 48, textAlign: 'center', color: C.textDim }}>Loading claims...</div>;
  }

  if (activeClaims.length === 0 && activeProposals.length === 0) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <div style={{ fontSize: 18, color: C.success, marginBottom: 8 }}>{'✓'} All claims triaged!</div>
        <p style={{ color: C.textDim, fontSize: 14 }}>No unreviewed claims remain.</p>
        <button onClick={onExit}
          style={{ marginTop: 16, fontSize: 13, padding: '8px 20px', borderRadius: 6,
            border: `1px solid ${C.border}`, background: 'transparent',
            color: C.text, cursor: 'pointer' }}>
          Back to Review
        </button>
      </div>
    );
  }

  // Build flat index map: claimId -> index (precomputed, no mutation in render)
  const claimIndexMap = {};
  let _idx = 0;
  for (const group of convGroups) {
    for (const claim of group.claims) {
      claimIndexMap[claim.id] = activeProposals.length + _idx;
      _idx++;
    }
  }

  return (
    <div style={{ padding: '24px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={onExit}
            style={{ fontSize: 13, padding: '4px 12px', borderRadius: 4,
              border: `1px solid ${C.border}`, background: 'transparent',
              color: C.textDim, cursor: 'pointer' }}>{'\u2190'} Back</button>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: C.text, margin: 0 }}>
            {'\u26A1'} Quick Pass
          </h1>
          <span style={{ fontSize: 13, color: C.textDim }}>
            {flatClaims.length} items remaining{activeProposals.length > 0 && ` (${activeProposals.length} proposals)`}
          </span>
        </div>
        <div style={{ fontSize: 11, color: C.textDim, display: 'flex', gap: 12 }}>
          <span><kbd style={{ padding: '1px 4px', borderRadius: 2, border: `1px solid ${C.border}`, fontSize: 10 }}>a</kbd> approve</span>
          <span><kbd style={{ padding: '1px 4px', borderRadius: 2, border: `1px solid ${C.border}`, fontSize: 10 }}>d</kbd> dismiss</span>
          <span><kbd style={{ padding: '1px 4px', borderRadius: 2, border: `1px solid ${C.border}`, fontSize: 10 }}>f</kbd> flag</span>
          <span><kbd style={{ padding: '1px 4px', borderRadius: 2, border: `1px solid ${C.border}`, fontSize: 10 }}>e</kbd> edit</span>
          <span><kbd style={{ padding: '1px 4px', borderRadius: 2, border: `1px solid ${C.border}`, fontSize: 10 }}>j/k</kbd> navigate</span>
        </div>
      </div>

      {/* Proposal cards (before conversation groups) */}
      {activeProposals.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ padding: '8px 14px', background: '#3b82f610', borderRadius: '6px 6px 0 0',
            borderBottom: `1px solid #3b82f633` }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: C.accent }}>
              {'\u{1F504}'} Belief Proposals
            </span>
            <span style={{ fontSize: 11, color: C.textDim, marginLeft: 8 }}>
              {activeProposals.length} pending
            </span>
          </div>
          <div style={{ border: '1px solid #3b82f633', borderTop: 'none',
            borderRadius: '0 0 6px 6px', padding: '8px' }}>
            {proposalItems.map((item, pIdx) => (
              <QuickPassProposalCard key={'p_' + item.id} proposal={item}
                isFocused={pIdx === focusIdx}
                onAccept={() => handleAcceptProposal(item.id)}
                onReject={() => handleRejectProposal(item.id)} />
            ))}
          </div>
        </div>
      )}

      {convGroups.map(group => {
        // groupStartIdx not needed — using precomputed claimIndexMap
        const allGroupTriaged = getConvTriageStatus(group.convId);

        const groupEl = (
          <div key={group.convId} style={{ marginBottom: 20 }}>
            {/* Conversation header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '8px 14px', background: C.card, borderRadius: '6px 6px 0 0',
              borderBottom: `1px solid ${C.border}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{group.title}</span>
                <span style={{ fontSize: 11, color: C.textDim }}>
                  {group.claims.length} claim{group.claims.length !== 1 ? 's' : ''}
                </span>
              </div>
              <span style={{ fontSize: 11, color: C.textDim }}>
                {relativeTime(group.captured_at)}
              </span>
            </div>

            {/* Claims */}
            <div style={{ border: `1px solid ${C.border}`, borderTop: 'none',
              borderRadius: '0 0 6px 6px', padding: '8px' }}>
              {group.claims.map(claim => {
                const idx = claimIndexMap[claim.id];
                return (
                  <QuickPassClaimCard key={claim.id} claim={claim}
                    isFocused={idx === focusIdx}
                    isEditing={editingIdx === idx}
                    editText={editText}
                    onEditChange={setEditText}
                    onEditSave={handleEditSave}
                    onEditCancel={() => setEditingIdx(null)}
                    onApprove={() => handleApprove(claim.id, claim.conversation_id)}
                    onDismiss={(errorType) => handleDismiss(claim.id, claim.conversation_id, errorType)}
                    onFlag={() => handleFlag(claim.conversation_id)}
                    onEdit={() => { setEditingIdx(idx); setEditText(claim.claim_text); }} />
                );
              })}
            </div>

            {/* "Ready to mark reviewed" prompt */}
            {allGroupTriaged && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '8px 14px', background: C.success + '10', borderRadius: 6,
                border: `1px solid ${C.success}30`, marginTop: 4 }}>
                <span style={{ fontSize: 12, color: C.success }}>
                  {'✓'} All claims reviewed
                </span>
                <button onClick={() => handleMarkReviewed(group.convId)}
                  style={{ fontSize: 12, padding: '4px 14px', borderRadius: 4, border: 'none',
                    background: C.success, color: '#fff', cursor: 'pointer', fontWeight: 600 }}>
                  Mark as Reviewed
                </button>
              </div>
            )}
          </div>
        );

        return groupEl;
      })}
    </div>
  );
}

function TriageCard({ convo, onPromote, onArchive, onDiscard }) {
  const [expanded, setExpanded] = useState(false);
  const [triageData, setTriageData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);

  const handleExpand = async () => {
    if (!expanded && !triageData) {
      setLoading(true);
      try {
        const data = await api.triageData(convo.id);
        setTriageData(data);
      } catch (e) {
        console.error('Failed to load triage data:', e);
      }
      setLoading(false);
    }
    setExpanded(!expanded);
  };

  const handlePromote = async () => {
    setActing(true);
    try {
      await onPromote(convo.id);
    } finally {
      setActing(false);
    }
  };

  const handleArchive = async () => {
    setActing(true);
    try {
      await onArchive(convo.id);
    } finally {
      setActing(false);
    }
  };

  const handleDiscard = async () => {
    if (!window.confirm('Discard this conversation? It will be permanently removed from review.')) return;
    setActing(true);
    try {
      if (onDiscard) await onDiscard(convo.id);
    } catch (e) { console.error('Discard failed', e); }
    setActing(false);
  };

  return (
    <div style={{ borderBottom: `1px solid ${C.border}` }}>
      <div
        onClick={handleExpand}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <StatusDot color={C.warning} />
          <span style={{ color: C.text, fontSize: 14 }}>
            {convo.manual_note || convo.title || (convo.source + " capture")}
            {convo.duration_seconds ? ` — ${Math.round(convo.duration_seconds / 60)}min` : ''}
          </span>
          <span style={{ color: C.textDim, fontSize: 12 }}>triaged low-value</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: C.textDim, fontSize: 12 }}>{relativeTime(convo.captured_at || convo.created_at)}</span>
          <span style={{ color: C.textDim, fontSize: 14 }}>{expanded ? '\u25B2' : '\u25BC'}</span>
        </div>
      </div>

      {expanded && (
        <div style={{ padding: '0 12px 16px 32px' }}>
          {loading ? (
            <div style={{ color: C.textDim, fontSize: 13 }}>Loading triage data...</div>
          ) : triageData ? (
            <div>
              {triageData.triage?.overall_value && (
                <div style={{ fontSize: 13, color: C.textMuted, marginBottom: 8 }}>
                  <strong>Value:</strong> {triageData.triage.overall_value}
                  {triageData.triage.value_reasoning && (
                    <span style={{ color: C.textDim }}> &mdash; {triageData.triage.value_reasoning}</span>
                  )}
                </div>
              )}
              {triageData.triage?.topic_tags && (
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
                  {triageData.triage.topic_tags.map((t, i) => (
                    <span key={i} style={{
                      fontSize: 11, padding: '2px 6px', borderRadius: 4,
                      background: C.border, color: C.textMuted,
                    }}>{t}</span>
                  ))}
                </div>
              )}
              {triageData.triage?.context_classification && (
                <div style={{ fontSize: 13, color: C.textDim, marginBottom: 8 }}>
                  Context: {triageData.triage.context_classification}
                </div>
              )}
              {triageData.episodes && triageData.episodes.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, color: C.textDim, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Episodes ({triageData.episodes.length})
                  </div>
                  {triageData.episodes.slice(0, 5).map((ep, i) => (
                    <div key={i} style={{ fontSize: 12, color: C.textMuted, padding: '2px 0' }}>
                      {ep.summary || ep.title || `Episode ${i + 1}`}
                    </div>
                  ))}
                  {triageData.episodes.length > 5 && (
                    <div style={{ fontSize: 11, color: C.textDim }}>...and {triageData.episodes.length - 5} more</div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: C.textDim }}>No triage data available</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              onClick={handlePromote} disabled={acting}
              style={{
                padding: '6px 14px', background: C.accent, color: '#fff', border: 'none',
                borderRadius: 6, fontSize: 12, cursor: 'pointer', opacity: acting ? 0.7 : 1,
              }}
            >
              {acting ? 'Processing...' : 'Promote to Full Extraction'}
            </button>
            <button
              onClick={handleArchive} disabled={acting}
              style={{
                padding: '6px 14px', background: 'transparent', color: C.textDim,
                border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 12, cursor: 'pointer',
                opacity: acting ? 0.7 : 1,
              }}
            >
              Archive as Low Value
            </button>
            <button
              onClick={handleDiscard} disabled={acting}
              style={{
                padding: '6px 14px', background: 'transparent', color: C.danger,
                border: '1px solid ' + C.danger + '33', borderRadius: 6, fontSize: 12,
                cursor: 'pointer', opacity: acting ? 0.7 : 1,
              }}
            >
              Discard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DuplicateContactBanner() {
  const [dupData, setDupData] = useState(null);
  const [resolving, setResolving] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    api.checkDuplicateContacts()
      .then(data => {
        if (data && data.status === 'duplicates_found') setDupData(data);
      })
      .catch(() => {});
  }, []);

  if (!dupData || dismissed) return null;

  const handleResolve = async () => {
    const groups = dupData.groups.map(g => g.contacts[0]?.canonical_name + ' (' + g.sauron_count + ' rows)').join(', ');
    if (!window.confirm('Merge duplicate contacts?\n\nGroups: ' + groups + '\n\nThis cannot be undone.')) return;
    setResolving(true);
    try {
      const result = await api.resolveDuplicateContacts();
      if (result && result.resolved > 0) {
        setDupData(null);
      }
    } catch (e) {
      console.error('Failed to resolve duplicates:', e);
    }
    setResolving(false);
  };

  const hasNetWarnings = dupData.networking_warnings && dupData.networking_warnings.length > 0;

  return (
    <div style={{
      background: C.warning + '15', border: `1px solid ${C.warning}40`, borderRadius: 8,
      padding: '12px 16px', marginBottom: 16, fontSize: 13,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>{'\u26A0'}</span>
          <span style={{ color: C.warning, fontWeight: 600 }}>
            {dupData.duplicate_count} duplicate contact group{dupData.duplicate_count > 1 ? 's' : ''} detected
          </span>
          <span style={{ color: C.textDim }}>
            ({dupData.total_extra_rows} extra row{dupData.total_extra_rows > 1 ? 's' : ''} in contacts)
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleResolve} disabled={resolving}
            style={{
              fontSize: 11, padding: '4px 12px', borderRadius: 4, cursor: 'pointer',
              background: C.accent + '22', color: C.accent, border: `1px solid ${C.accent}44`,
              fontWeight: 600,
            }}>
            {resolving ? 'Resolving...' : 'Auto-resolve'}
          </button>
          <button onClick={() => setDismissed(true)}
            style={{
              fontSize: 11, padding: '4px 8px', borderRadius: 4, cursor: 'pointer',
              background: 'transparent', color: C.textDim, border: `1px solid ${C.border}`,
            }}>
            Dismiss
          </button>
        </div>
      </div>
      {hasNetWarnings && (
        <div style={{ marginTop: 8, padding: '8px 12px', background: C.error + '12',
          borderRadius: 4, border: `1px solid ${C.error}30` }}>
          <span style={{ color: C.error, fontWeight: 600, fontSize: 12 }}>
            {'\u26D4'} Networking app warnings:
          </span>
          {dupData.networking_warnings.map((w, i) => (
            <div key={i} style={{ color: C.textDim, fontSize: 12, marginTop: 4 }}>
              {w.warning}
            </div>
          ))}
        </div>
      )}
      <div style={{ marginTop: 8, fontSize: 12, color: C.textDim }}>
        {dupData.groups.map(g => (
          <span key={g.networking_app_contact_id} style={{ marginRight: 12 }}>
            {g.contacts[0]?.canonical_name} ({g.sauron_count} rows)
            {g.networking_app_status?.exists ? ' \u2713' : ' \u2717'}
          </span>
        ))}
      </div>
    </div>
  );
}



// ═══════════════════════════════════════════════════════
// PROVISIONAL ORG CARD — for organization review section
// ═══════════════════════════════════════════════════════

function OrgSearchDropdown({ onSelect, onCancel, placeholder }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  const doSearch = useCallback(async (q) => {
    if (q.length < 2) { setResults([]); return; }
    setSearching(true);
    try {
      const data = await searchNetworkingOrgs(q);
      setResults(Array.isArray(data) ? data : data.organizations || []);
    } catch (e) {
      console.error('Org search failed:', e);
      setResults([]);
    }
    setSearching(false);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => doSearch(query), 300);
    return () => clearTimeout(timer);
  }, [query, doSearch]);

  return (
    <div style={{ marginTop: 8, padding: 8, background: C.bg, border: `1px solid ${C.border}`,
      borderRadius: 6 }}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
        <input
          type="text" value={query} onChange={e => setQuery(e.target.value)}
          placeholder={placeholder || 'Search organizations...'}
          autoFocus
          style={{ flex: 1, fontSize: 12, padding: '4px 8px', borderRadius: 4,
            border: `1px solid ${C.border}`, background: C.card, color: C.text }}
        />
        <button onClick={onCancel}
          style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3,
            border: `1px solid ${C.border}`, background: 'transparent',
            color: C.textDim, cursor: 'pointer' }}>Cancel</button>
      </div>
      {searching && <div style={{ fontSize: 11, color: C.textDim, padding: 4 }}>Searching...</div>}
      {results.length > 0 && (
        <div style={{ maxHeight: 150, overflowY: 'auto' }}>
          {results.map(org => (
            <div key={org.id} onClick={() => onSelect(org)}
              style={{ padding: '6px 8px', fontSize: 12, color: C.text, cursor: 'pointer',
                borderRadius: 4, display: 'flex', justifyContent: 'space-between' }}
              onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span>{org.name}</span>
              {org.industry && <span style={{ color: C.textDim, fontSize: 11 }}>{org.industry}</span>}
            </div>
          ))}
        </div>
      )}
      {query.length >= 2 && !searching && results.length === 0 && (
        <div style={{ fontSize: 11, color: C.textDim, padding: 4 }}>No organizations found</div>
      )}
    </div>
  );
}

function ProvisionalOrgCard({ group, onAction }) {
  const [acting, setActing] = useState(false);
  const [actionMode, setActionMode] = useState(null); // 'link' | 'sub-org'
  const [result, setResult] = useState(null);

  const firstSuggestion = group.suggestions[0];

  const handleCreate = async () => {
    setActing(true);
    try {
      const res = await approveProvisionalOrg(firstSuggestion.id);
      setResult({ type: 'success', message: `Created "${res.org_name}" (${res.org_id})` });
      onAction();
    } catch (e) {
      setResult({ type: 'error', message: e.message });
    }
    setActing(false);
  };

  const handleCreateSubOrg = async (parentOrg) => {
    setActing(true);
    try {
      const res = await approveProvisionalOrg(firstSuggestion.id, parentOrg.id);
      setResult({ type: 'success', message: `Created "${res.org_name}" under ${parentOrg.name}` });
      setActionMode(null);
      onAction();
    } catch (e) {
      setResult({ type: 'error', message: e.message });
    }
    setActing(false);
  };

  const handleLink = async (targetOrg) => {
    setActing(true);
    try {
      await mergeProvisionalOrg(firstSuggestion.id, targetOrg.id);
      setResult({ type: 'success', message: `Linked to "${targetOrg.name}"` });
      setActionMode(null);
      onAction();
    } catch (e) {
      setResult({ type: 'error', message: e.message });
    }
    setActing(false);
  };

  const handleDismiss = async () => {
    setActing(true);
    try {
      await dismissProvisionalOrg(firstSuggestion.id);
      setResult({ type: 'success', message: 'Dismissed' });
      onAction();
    } catch (e) {
      setResult({ type: 'error', message: e.message });
    }
    setActing(false);
  };

  if (result && result.type === 'success') {
    return (
      <div style={{ padding: '10px 14px', borderRadius: 6, border: `1px solid ${C.success}33`,
        background: C.success + '08', marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: C.success }}>{'\u2713'} {result.message}</span>
      </div>
    );
  }

  return (
    <div style={{ padding: '12px 14px', borderRadius: 6, border: `1px solid ${C.border}`,
      background: C.card, marginBottom: 8 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{group.display_name}</span>
          {group.count > 1 && (
            <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 10,
              background: C.accent + '22', color: C.accent }}>
              {group.count} mention{group.count !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        {group.suggested_by && group.suggested_by.length > 0 && (
          <span style={{ fontSize: 10, color: C.textDim }}>
            via {group.suggested_by.join(', ')}
          </span>
        )}
      </div>

      {/* Context from first suggestion */}
      {firstSuggestion.source_context && (
        <div style={{ fontSize: 12, color: C.textDim, marginBottom: 8, lineHeight: 1.4 }}>
          {firstSuggestion.source_context}
        </div>
      )}
      {firstSuggestion.resolution_source_context && (
        <div style={{ fontSize: 11, color: C.textDim, fontStyle: 'italic', marginBottom: 8 }}>
          Resolution: {firstSuggestion.resolution_source_context}
        </div>
      )}

      {/* Actions */}
      {!actionMode && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={handleCreate} disabled={acting}
            style={{ fontSize: 11, padding: '4px 10px', borderRadius: 4,
              border: `1px solid ${C.success}44`, background: C.success + '10',
              color: C.success, cursor: acting ? 'wait' : 'pointer' }}>
            + Create
          </button>
          <button onClick={() => setActionMode('sub-org')} disabled={acting}
            style={{ fontSize: 11, padding: '4px 10px', borderRadius: 4,
              border: `1px solid ${C.accent}44`, background: C.accent + '10',
              color: C.accent, cursor: acting ? 'wait' : 'pointer' }}>
            └ Create as Sub-Org
          </button>
          <button onClick={() => setActionMode('link')} disabled={acting}
            style={{ fontSize: 11, padding: '4px 10px', borderRadius: 4,
              border: `1px solid ${C.purple}44`, background: C.purple + '10',
              color: C.purple, cursor: acting ? 'wait' : 'pointer' }}>
            → Link to Existing
          </button>
          <button onClick={handleDismiss} disabled={acting}
            style={{ fontSize: 11, padding: '4px 10px', borderRadius: 4,
              border: `1px solid ${C.danger}44`, background: 'transparent',
              color: C.danger, cursor: acting ? 'wait' : 'pointer', opacity: 0.8 }}>
            ✗ Dismiss
          </button>
        </div>
      )}

      {/* Sub-org search */}
      {actionMode === 'sub-org' && (
        <OrgSearchDropdown
          placeholder="Search for parent organization..."
          onSelect={handleCreateSubOrg}
          onCancel={() => setActionMode(null)}
        />
      )}

      {/* Link/merge search */}
      {actionMode === 'link' && (
        <OrgSearchDropdown
          placeholder="Search for organization to link to..."
          onSelect={handleLink}
          onCancel={() => setActionMode(null)}
        />
      )}

      {result && result.type === 'error' && (
        <div style={{ marginTop: 6, fontSize: 11, color: C.danger }}>{result.message}</div>
      )}
    </div>
  );
}

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
