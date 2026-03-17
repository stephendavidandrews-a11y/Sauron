import { useState, useEffect, useCallback } from 'react';
import { api } from '../../../api';
import { C, cardStyle, claimTypeColors } from '../styles';
import { ClaimRow } from '../claims/ClaimRow';

export function ClaimsTab({ claims: initialClaims, conversationId, contacts, updateClaim, onActionError }) {
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
      updateClaim(claim.id, { claim_text: editText, review_status: 'user_corrected', text_user_edited: true });
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
        updateClaim(claim.id, { claim_text: result.updated_text, display_overrides: null });
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
                } catch (e) {
                  console.error('Approve failed', e);
                  if (onActionError) onActionError('Approve failed \u2014 please retry');
                }
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
