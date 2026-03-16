import { useState } from 'react';
import { api } from '../../../api';
import { C, cardStyle, claimTypeColors } from '../styles';
import { ClaimTextWithOverrides } from './ClaimTextWithOverrides';
import { EntityChips } from './EntityChips';
import { ErrorTypeDropdown } from './ErrorTypeDropdown';
import { CommitmentEditPanel } from './CommitmentEditPanel';

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

