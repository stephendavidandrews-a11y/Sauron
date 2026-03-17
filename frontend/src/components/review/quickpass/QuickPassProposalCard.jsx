import { useRef, useEffect } from 'react';
import { C } from "../../../utils/colors";

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
