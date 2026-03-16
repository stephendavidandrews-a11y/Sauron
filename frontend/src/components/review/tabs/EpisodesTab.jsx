import { useState, useEffect, useCallback } from 'react';
import { api } from '../../../api';
import { C, cardStyle, claimTypeColors } from '../styles';
import { ClaimRow } from '../claims/ClaimRow';
import { AddClaimForm } from '../claims/AddClaimForm';
import { EntityChips } from '../claims/EntityChips';

export function EpisodesTab({ episodes: initialEpisodes, claims: initialClaims, conversationId, contacts, updateClaim, addClaimToState, onActionError }) {
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
      if (onActionError) onActionError('Approve failed \u2014 please retry');
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
      if (onActionError) onActionError('Approve all failed \u2014 please retry');
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
        updateClaim(claim.id, { claim_text: result.updated_text, display_overrides: null });
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
      const remainingEntities = (claim.entities || []).filter(e => e.id !== entityLinkId);
      const subjectEntities = remainingEntities.filter(e => e.role === 'subject');
      const updates = { entities: remainingEntities };
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
                        <button data-testid={`approve-all-${ep.id}`} onClick={(e) => { e.stopPropagation(); handleApproveAll(ep.id); }}
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

