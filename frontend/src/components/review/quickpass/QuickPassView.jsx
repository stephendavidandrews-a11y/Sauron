import React, { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../../api';
import { C } from "../../../utils/colors";
import { relativeTime } from "../../../utils/time";
import { QuickPassClaimCard } from './QuickPassClaimCard';
import { QuickPassProposalCard } from './QuickPassProposalCard';

export function QuickPassView({ onExit, onMarkReviewed }) {
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
  const flatClaimsRef = React.useRef(flatClaims);
  flatClaimsRef.current = flatClaims;
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

      const claim = flatClaimsRef.current[focusIdx];
      if (!claim && !['Escape'].includes(e.key)) return;

      switch (e.key) {
        case 'j':
        case 'ArrowDown':
          e.preventDefault();
          setFocusIdx(prev => Math.min(prev + 1, flatClaimsRef.current.length - 1));
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
  }, [focusIdx, showDismissPicker]);

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
