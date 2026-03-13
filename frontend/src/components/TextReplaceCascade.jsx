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
  conversations: 'Conversation',
  event_claims: 'Claims',
  event_episodes: 'Episodes',
  graph_edges: 'Graph Edges',
  beliefs: 'Beliefs',
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

export default function TextReplaceCascade({
  conversationId,
  defaultFindText,
  defaultReplaceWith,
  onComplete,
  onDismiss,
}) {
  const [findText, setFindText] = useState(defaultFindText || '');
  const [replaceWith, setReplaceWith] = useState(defaultReplaceWith || '');
  const [preview, setPreview] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [dismissed, setDismissed] = useState(new Set());
  const [editOverrides, setEditOverrides] = useState({});
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(true);

  const handlePreview = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.previewTextReplace(
        conversationId,
        findText.trim(),
        replaceWith.trim()
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
      setDismissed(new Set());
      setEditOverrides({});
    } catch (e) {
      setError(e.message || 'Preview failed');
    }
    setLoading(false);
  };

  const handleApply = async () => {
    setApplying(true);
    setError(null);
    try {
      const editedChanges = Object.entries(editOverrides).map(([id, text]) => ({
        id,
        custom_text: text,
      }));
      const data = await api.applyTextReplace(
        conversationId,
        findText.trim(),
        replaceWith.trim(),
        [...selected],
        editedChanges
      );
      setResult(data);
      if (onComplete) onComplete();
    } catch (e) {
      setError(e.message || 'Apply failed');
    }
    setApplying(false);
  };

  const toggleChange = (changeId) => {
    if (dismissed.has(changeId)) return;
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(changeId)) next.delete(changeId);
      else next.add(changeId);
      return next;
    });
  };

  const dismissChange = (changeId) => {
    setDismissed(prev => {
      const next = new Set(prev);
      next.add(changeId);
      return next;
    });
    setSelected(prev => {
      const next = new Set(prev);
      next.delete(changeId);
      return next;
    });
  };

  const selectAll = (filter) => {
    if (!preview) return;
    const next = new Set();
    for (const c of preview.changes) {
      if (c.skipped || dismissed.has(c.change_id)) continue;
      if (filter === 'high' && c.confidence !== 'high') continue;
      next.add(c.change_id);
    }
    setSelected(next);
  };

  const deselectAll = () => setSelected(new Set());

  const startEdit = (changeId, currentAfter) => {
    setEditingId(changeId);
    if (!editOverrides[changeId]) {
      setEditOverrides(prev => ({ ...prev, [changeId]: currentAfter }));
    }
  };

  const updateEdit = (changeId, text) => {
    setEditOverrides(prev => ({ ...prev, [changeId]: text }));
  };

  const cancelEdit = (changeId) => {
    setEditingId(null);
    setEditOverrides(prev => {
      const next = { ...prev };
      delete next[changeId];
      return next;
    });
  };

  const saveEdit = () => setEditingId(null);

  // Group changes by table
  const grouped = {};
  if (preview) {
    for (const c of preview.changes) {
      const key = c.table;
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(c);
    }
  }

  const inputStyle = {
    width: '100%', padding: '6px 10px', fontSize: 13,
    background: C.card, color: C.text, border: `1px solid ${C.border}`,
    borderRadius: 6, outline: 'none', boxSizing: 'border-box',
  };

  const btnStyle = (color, disabled) => ({
    padding: '6px 14px', fontSize: 12, fontWeight: 600, borderRadius: 6,
    border: 'none', cursor: disabled ? 'default' : 'pointer',
    background: disabled ? C.card : color + '22',
    color: disabled ? C.textDim : color,
    opacity: disabled ? 0.5 : 1,
  });

  const smallBtn = (color) => ({
    padding: '2px 8px', fontSize: 10, fontWeight: 500, borderRadius: 4,
    border: 'none', cursor: 'pointer',
    background: color + '22', color: color,
  });

  return (
    <div style={{
      margin: '8px 0', border: `1px solid ${C.accent}44`,
      borderRadius: 8, background: C.bg, overflow: 'hidden',
    }}>
      {/* Accordion header */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', cursor: 'pointer',
          background: C.accent + '11',
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: C.accent }}>
          {result ? '\u2705 Text replacement complete' : '\uD83D\uDD0D Fix text in this conversation'}
        </span>
        <span style={{ color: C.textDim, fontSize: 12 }}>
          {expanded ? '\u25B2' : '\u25BC'}
        </span>
      </div>

      {expanded && (
        <div style={{ padding: '12px 14px' }}>
          {/* Result state */}
          {result && (
            <div style={{
              padding: 12, background: C.success + '15', border: `1px solid ${C.success}44`,
              borderRadius: 6, fontSize: 12, color: C.text, lineHeight: 1.6,
            }}>
              <div>Applied: {result.applied} changes</div>
              <div>Skipped: {result.skipped}</div>
              <div>Re-embedded: {result.re_embedded} items</div>
              {result.beliefs_affected > 0 && (
                <div>Beliefs queued for review: {result.beliefs_affected}</div>
              )}
            </div>
          )}

          {/* Input state */}
          {!result && !preview && (
            <>
              <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>
                    Find
                  </label>
                  <input
                    value={findText}
                    onChange={e => setFindText(e.target.value)}
                    placeholder="Text to find"
                    style={inputStyle}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>
                    Replace with
                  </label>
                  <input
                    value={replaceWith}
                    onChange={e => setReplaceWith(e.target.value)}
                    placeholder="Replacement text"
                    style={inputStyle}
                  />
                </div>
              </div>
              {error && <div style={{ color: C.danger, fontSize: 11, marginBottom: 8 }}>{error}</div>}
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={handlePreview}
                  disabled={!findText.trim() || !replaceWith.trim() || loading}
                  style={btnStyle(C.accent, !findText.trim() || !replaceWith.trim() || loading)}
                >
                  {loading ? 'Scanning...' : 'Preview Changes'}
                </button>
                <button onClick={onDismiss} style={btnStyle(C.textDim, false)}>
                  Skip
                </button>
              </div>
            </>
          )}

          {/* Preview state */}
          {!result && preview && (
            <>
              {/* Empty state */}
              {preview.changes.length === 0 && (
                <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 12 }}>
                  No matching text found in this conversation.
                </div>
              )}

              {preview.changes.length > 0 && (
                <>
                  {/* Summary bar */}
                  <div style={{
                    padding: '8px 12px', background: C.card, borderRadius: 6,
                    marginBottom: 12, fontSize: 11, color: C.textMuted,
                    display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap',
                  }}>
                    <span>{preview.summary.total} changes found</span>
                    <span style={{ color: C.success }}>{preview.summary.high_confidence} high</span>
                    <span style={{ color: C.warning }}>{preview.summary.medium_confidence} medium</span>
                    {preview.summary.skipped > 0 && (
                      <span style={{ color: C.textDim }}>{preview.summary.skipped} skipped</span>
                    )}
                    <span style={{ marginLeft: 'auto', color: C.accent }}>{selected.size} selected</span>
                  </div>

                  {/* Quick select buttons */}
                  <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
                    <button onClick={() => selectAll('high')} style={smallBtn(C.success)}>
                      Select All High
                    </button>
                    <button onClick={() => selectAll('all')} style={smallBtn(C.accent)}>
                      Select All
                    </button>
                    <button onClick={deselectAll} style={smallBtn(C.textDim)}>
                      Deselect All
                    </button>
                  </div>

                  {/* Grouped changes */}
                  {Object.entries(grouped).map(([table, items]) => (
                    <div key={table} style={{ marginBottom: 12 }}>
                      <h4 style={{
                        fontSize: 10, fontWeight: 600, color: C.textMuted,
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                        marginBottom: 6, marginTop: 0,
                      }}>
                        {TABLE_LABELS[table] || table} ({items.length})
                      </h4>
                      {items.map(c => {
                        const isDismissed = dismissed.has(c.change_id);
                        const isEditing = editingId === c.change_id;
                        const displayAfter = editOverrides[c.change_id] || c.after;

                        return (
                          <div key={c.change_id} style={{
                            display: 'flex', gap: 8, alignItems: 'flex-start',
                            padding: '6px 8px', borderRadius: 6,
                            background: (c.skipped || isDismissed) ? C.card + '44' : C.card,
                            border: `1px solid ${C.border}`,
                            marginBottom: 3,
                            opacity: (c.skipped || isDismissed) ? 0.4 : 1,
                            textDecoration: isDismissed ? 'line-through' : 'none',
                          }}>
                            <input
                              type="checkbox"
                              checked={selected.has(c.change_id)}
                              onChange={() => toggleChange(c.change_id)}
                              disabled={c.skipped || isDismissed}
                              style={{ marginTop: 3, flexShrink: 0 }}
                            />
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 3 }}>
                                <span style={{
                                  fontSize: 9, padding: '1px 5px', borderRadius: 3,
                                  background: (CONFIDENCE_COLORS[c.confidence] || C.textDim) + '22',
                                  color: CONFIDENCE_COLORS[c.confidence] || C.textDim,
                                  fontWeight: 500,
                                }}>
                                  {c.confidence}
                                </span>
                                <span style={{ fontSize: 10, color: C.textDim }}>
                                  {c.field}
                                </span>
                                {c.skip_reason && (
                                  <span style={{ fontSize: 10, color: C.danger }}>
                                    {c.skip_reason}
                                  </span>
                                )}
                              </div>

                              {isEditing ? (
                                <div style={{ marginTop: 4 }}>
                                  <div style={{ fontSize: 11, color: C.textDim, marginBottom: 2 }}>
                                    Original: <span style={{ color: C.danger }}>{c.before.slice(0, 120)}</span>
                                  </div>
                                  <textarea
                                    value={editOverrides[c.change_id] || ''}
                                    onChange={e => updateEdit(c.change_id, e.target.value)}
                                    style={{
                                      ...inputStyle, fontSize: 12, minHeight: 50,
                                      resize: 'vertical', fontFamily: 'inherit',
                                    }}
                                  />
                                  <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                                    <button onClick={saveEdit} style={smallBtn(C.success)}>Save</button>
                                    <button onClick={() => cancelEdit(c.change_id)} style={smallBtn(C.textDim)}>Cancel</button>
                                  </div>
                                </div>
                              ) : (
                                <DiffText before={c.before} after={displayAfter} />
                              )}
                            </div>

                            {/* Action buttons */}
                            {!c.skipped && !isDismissed && !isEditing && (
                              <div style={{ display: 'flex', gap: 4, flexShrink: 0, marginTop: 2 }}>
                                <button
                                  onClick={() => startEdit(c.change_id, displayAfter)}
                                  style={smallBtn(C.accent)}
                                  title="Edit replacement"
                                >
                                  Edit
                                </button>
                                <button
                                  onClick={() => dismissChange(c.change_id)}
                                  style={smallBtn(C.danger)}
                                  title="Dismiss this change"
                                >
                                  &times;
                                </button>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </>
              )}

              {/* Action buttons */}
              {error && <div style={{ color: C.danger, fontSize: 11, marginBottom: 8 }}>{error}</div>}
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button onClick={() => { setPreview(null); setError(null); }} style={btnStyle(C.textDim, false)}>
                  Back
                </button>
                {preview.changes.length > 0 && (
                  <button
                    onClick={handleApply}
                    disabled={selected.size === 0 || applying}
                    style={btnStyle(C.success, selected.size === 0 || applying)}
                  >
                    {applying ? 'Applying...' : `Apply ${selected.size} Changes`}
                  </button>
                )}
                <button onClick={onDismiss} style={btnStyle(C.textDim, false)}>
                  Skip
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
