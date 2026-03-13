import { useState } from 'react';
import { api } from '../api';

const C = {
  bg: '#0a0f1a', card: '#111827', cardHover: '#1a2234',
  border: '#1f2937', text: '#e5e7eb',
  textMuted: '#9ca3af', textDim: '#6b7280',
  accent: '#3b82f6', success: '#10b981', warning: '#f59e0b',
  danger: '#ef4444', purple: '#a78bfa',
};

const CONFIDENCE_COLORS = {
  high: C.success,
  medium: C.warning,
  skipped: C.textDim,
};

const TABLE_LABELS = {
  unified_contacts: 'Contact',
  event_claims: 'Claims',
  event_episodes: 'Episodes',
  graph_edges: 'Graph Edges',
  beliefs: 'Beliefs',
  conversations: 'Conversations',
};

function DiffText({ before, after }) {
  return (
    <div style={{ fontSize: 12, lineHeight: 1.6 }}>
      <div style={{ color: C.danger, textDecoration: 'line-through', opacity: 0.7 }}>
        {before.length > 200 ? before.slice(0, 200) + '...' : before}
      </div>
      <div style={{ color: C.success }}>
        {after.length > 200 ? after.slice(0, 200) + '...' : after}
      </div>
    </div>
  );
}

export default function RenamePreview({ contact, onClose, onApplied }) {
  const [newName, setNewName] = useState('');
  const [oldNameOverride, setOldNameOverride] = useState('');
  const [preview, setPreview] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [showOverride, setShowOverride] = useState(false);

  const handlePreview = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.previewRename(
        contact.id,
        newName.trim(),
        oldNameOverride.trim() || undefined
      );
      setPreview(data);
      // Pre-select HIGH confidence, non-skipped changes
      const autoSelected = new Set();
      for (const c of data.changes) {
        if (c.confidence === 'high' && !c.skipped) {
          autoSelected.add(c.change_id);
        }
      }
      setSelected(autoSelected);
    } catch (e) {
      setError(e.message || 'Preview failed');
    }
    setLoading(false);
  };

  const handleApply = async () => {
    if (!window.confirm(
      `Rename "${preview.old_name}" to "${preview.new_name}" across ${selected.size} records? This cannot be undone.`
    )) return;
    setApplying(true);
    setError(null);
    try {
      const data = await api.applyRename(
        contact.id,
        newName.trim(),
        [...selected],
        oldNameOverride.trim() || undefined
      );
      setResult(data);
      if (onApplied) onApplied();
    } catch (e) {
      setError(e.message || 'Apply failed');
    }
    setApplying(false);
  };

  const toggleChange = (changeId) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(changeId)) next.delete(changeId);
      else next.add(changeId);
      return next;
    });
  };

  const selectAll = (filter) => {
    if (!preview) return;
    const next = new Set();
    for (const c of preview.changes) {
      if (c.skipped) continue;
      if (filter === 'high' && c.confidence !== 'high') continue;
      next.add(c.change_id);
    }
    setSelected(next);
  };

  // Group changes by table
  const grouped = {};
  if (preview) {
    for (const c of preview.changes) {
      const key = c.table;
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(c);
    }
  }

  const overlayStyle = {
    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
    background: 'rgba(0,0,0,0.7)', zIndex: 1000,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  };

  const modalStyle = {
    background: C.bg, border: `1px solid ${C.border}`, borderRadius: 12,
    width: '90%', maxWidth: 800, maxHeight: '85vh', overflow: 'auto',
    padding: 24,
  };

  const inputStyle = {
    width: '100%', padding: '8px 12px', fontSize: 14,
    background: C.card, color: C.text, border: `1px solid ${C.border}`,
    borderRadius: 6, outline: 'none', boxSizing: 'border-box',
  };

  const btnStyle = (color, disabled) => ({
    padding: '8px 16px', fontSize: 13, fontWeight: 600, borderRadius: 6,
    border: 'none', cursor: disabled ? 'default' : 'pointer',
    background: disabled ? C.card : color + '22',
    color: disabled ? C.textDim : color,
    opacity: disabled ? 0.5 : 1,
  });

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={modalStyle} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: C.text, margin: 0 }}>
            Rename Contact
          </h2>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: C.textDim,
            fontSize: 20, cursor: 'pointer',
          }}>&times;</button>
        </div>

        {/* Result state */}
        {result && (
          <div style={{
            padding: 16, background: C.success + '15', border: `1px solid ${C.success}44`,
            borderRadius: 8, marginBottom: 16,
          }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.success, marginBottom: 8 }}>
              Rename Complete
            </div>
            <div style={{ fontSize: 12, color: C.text, lineHeight: 1.6 }}>
              <div>Applied: {result.applied} changes</div>
              <div>Skipped: {result.skipped}</div>
              <div>Re-embedded: {result.re_embedded} items</div>
              <div>Beliefs queued for re-synthesis: {result.beliefs_queued_for_resynthesis}</div>
              {result.alias_saved && <div>Alias saved: "{result.alias_saved}"</div>}
            </div>
            <button onClick={onClose} style={{ ...btnStyle(C.accent, false), marginTop: 12 }}>
              Close
            </button>
          </div>
        )}

        {/* Input state */}
        {!result && !preview && (
          <>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, color: C.textDim, display: 'block', marginBottom: 4 }}>
                Current Name
              </label>
              <input value={contact.canonical_name} disabled style={{ ...inputStyle, opacity: 0.6 }} />
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, color: C.textDim, display: 'block', marginBottom: 4 }}>
                New Name
              </label>
              <input
                value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="Enter corrected name"
                style={inputStyle}
                autoFocus
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <button
                onClick={() => setShowOverride(!showOverride)}
                style={{ background: 'none', border: 'none', color: C.accent, fontSize: 11, cursor: 'pointer', padding: 0 }}
              >
                {showOverride ? 'Hide' : 'Show'} old name override (advanced)
              </button>
              {showOverride && (
                <div style={{ marginTop: 8 }}>
                  <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 4 }}>
                    Old name to search for (if different from current canonical name)
                  </label>
                  <input
                    value={oldNameOverride}
                    onChange={e => setOldNameOverride(e.target.value)}
                    placeholder="e.g., Wieden"
                    style={{ ...inputStyle, fontSize: 12 }}
                  />
                </div>
              )}
            </div>
            {error && <div style={{ color: C.danger, fontSize: 12, marginBottom: 12 }}>{error}</div>}
            <button
              onClick={handlePreview}
              disabled={!newName.trim() || loading}
              style={btnStyle(C.accent, !newName.trim() || loading)}
            >
              {loading ? 'Scanning...' : 'Preview Changes'}
            </button>
          </>
        )}

        {/* Preview state */}
        {!result && preview && (
          <>
            {/* Summary bar */}
            <div style={{
              padding: '10px 14px', background: C.card, borderRadius: 6,
              marginBottom: 16, fontSize: 12, color: C.textMuted,
              display: 'flex', gap: 16, alignItems: 'center',
            }}>
              <span>{preview.summary.total} changes found</span>
              <span style={{ color: C.success }}>{preview.summary.high_confidence} high</span>
              <span style={{ color: C.warning }}>{preview.summary.medium_confidence} medium</span>
              <span style={{ color: C.textDim }}>{preview.summary.skipped} skipped</span>
              <span style={{ marginLeft: 'auto', color: C.accent }}>{selected.size} selected</span>
            </div>

            {/* Quick select buttons */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <button onClick={() => selectAll('high')} style={btnStyle(C.success, false)}>
                Select All High
              </button>
              <button onClick={() => selectAll('all')} style={btnStyle(C.accent, false)}>
                Select All
              </button>
              <button onClick={() => setSelected(new Set())} style={btnStyle(C.textDim, false)}>
                Deselect All
              </button>
            </div>

            {/* Grouped changes */}
            {Object.entries(grouped).map(([table, items]) => (
              <div key={table} style={{ marginBottom: 16 }}>
                <h4 style={{
                  fontSize: 11, fontWeight: 600, color: C.textMuted,
                  textTransform: 'uppercase', letterSpacing: '0.05em',
                  marginBottom: 8, marginTop: 0,
                }}>
                  {TABLE_LABELS[table] || table} ({items.length})
                </h4>
                {items.map(c => (
                  <div key={c.change_id} style={{
                    display: 'flex', gap: 10, alignItems: 'flex-start',
                    padding: '8px 10px', borderRadius: 6,
                    background: c.skipped ? C.card + '44' : C.card,
                    border: `1px solid ${C.border}`,
                    marginBottom: 4,
                    opacity: c.skipped ? 0.5 : 1,
                  }}>
                    <input
                      type="checkbox"
                      checked={selected.has(c.change_id)}
                      onChange={() => toggleChange(c.change_id)}
                      disabled={c.skipped}
                      style={{ marginTop: 4, flexShrink: 0 }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                        <span style={{
                          fontSize: 10, padding: '1px 6px', borderRadius: 3,
                          background: CONFIDENCE_COLORS[c.confidence] + '22',
                          color: CONFIDENCE_COLORS[c.confidence],
                          fontWeight: 500,
                        }}>
                          {c.confidence}
                        </span>
                        <span style={{ fontSize: 10, color: C.textDim }}>
                          {c.field}
                          {c.register !== 'n/a' && ` (${c.register})`}
                        </span>
                        {c.skip_reason && (
                          <span style={{ fontSize: 10, color: C.danger }}>
                            {c.skip_reason}
                          </span>
                        )}
                      </div>
                      <DiffText before={c.before} after={c.after} />
                    </div>
                  </div>
                ))}
              </div>
            ))}

            {/* Action buttons */}
            {error && <div style={{ color: C.danger, fontSize: 12, marginBottom: 12 }}>{error}</div>}
            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button onClick={() => setPreview(null)} style={btnStyle(C.textDim, false)}>
                Back
              </button>
              <button
                onClick={handleApply}
                disabled={selected.size === 0 || applying}
                style={btnStyle(C.success, selected.size === 0 || applying)}
              >
                {applying ? 'Applying...' : `Apply ${selected.size} Changes`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
