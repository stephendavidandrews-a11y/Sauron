import { useEffect } from 'react';
import { C } from "../../../utils/colors";

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
