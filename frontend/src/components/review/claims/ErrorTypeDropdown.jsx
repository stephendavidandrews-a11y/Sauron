import { useState } from 'react';
import { C } from "../../../utils/colors";
import { errorTypes } from '../styles';

export function ErrorTypeDropdown({ claim, onSelect }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => setOpen(!open)}
        style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, border: `1px solid ${C.border}`,
          background: 'transparent', color: C.danger, cursor: 'pointer' }}>Flag</button>
      {open && (
        <div style={{ position: 'absolute', right: 0, top: '100%', marginTop: 4, zIndex: 50,
          background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, padding: 4,
          minWidth: 240, boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
          {errorTypes.map(et => (
            <button key={et.value} onClick={() => { onSelect(claim, et.value); setOpen(false); }}
              style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 10px',
                fontSize: 12, color: C.textMuted, background: 'transparent', border: 'none', cursor: 'pointer', borderRadius: 4 }}
              onMouseEnter={e => e.target.style.background = C.cardHover}
              onMouseLeave={e => e.target.style.background = 'transparent'}>
              {et.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// TRANSCRIPT TAB — Speaker correction + text editing
// ═══════════════════════════════════════════════════════
