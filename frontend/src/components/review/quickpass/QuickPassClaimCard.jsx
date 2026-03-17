import { useState, useRef, useEffect } from 'react';
import { C } from "../../../utils/colors";
import { QuickPassErrorPicker } from './QuickPassErrorPicker';

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
            <span style={{ opacity: 0.5, marginRight: 3 }}>a</span>{'\u2713'} Approve
          </button>
          <button onClick={() => setShowDismiss(true)}
            style={{ fontSize: 11, padding: '3px 10px', borderRadius: 3, border: `1px solid ${C.danger}44`,
              background: showDismiss ? C.danger + '10' : 'transparent', color: C.danger, cursor: 'pointer' }}>
            <span style={{ opacity: 0.5, marginRight: 3 }}>d</span>{'\u2717'} Dismiss
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
