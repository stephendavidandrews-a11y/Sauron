import { useState, useEffect } from 'react';
import { fetchGraphEdges, confirmGraphEdge, dismissGraphEdge, updateGraphEdge } from '../../../api';
import { C, cardStyle, OBJECT_TYPE_LABELS } from '../styles';

export function GraphEdgeReviewBanner({ conversationId, refreshKey }) {
  const [edges, setEdges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editType, setEditType] = useState('');
  const [actionLoading, setActionLoading] = useState(null);

  useEffect(() => {
    fetchGraphEdges(conversationId)
      .then(d => setEdges(d.edges || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conversationId, refreshKey]);

  if (loading) return null;

  const pending = edges.filter(e => e.review_status === 'pending');
  const confirmed = edges.filter(e => e.review_status === 'confirmed');
  const dismissed = edges.filter(e => e.review_status === 'dismissed');

  const handleConfirm = async (edgeId) => {
    setActionLoading(edgeId);
    try {
      const updated = await confirmGraphEdge(edgeId);
      setEdges(prev => prev.map(e => e.id === edgeId ? { ...e, ...updated } : e));
    } catch (e) { console.error('Confirm edge failed', e); }
    setActionLoading(null);
  };

  const handleDismiss = async (edgeId) => {
    setActionLoading(edgeId);
    try {
      const updated = await dismissGraphEdge(edgeId);
      setEdges(prev => prev.map(e => e.id === edgeId ? { ...e, ...updated } : e));
    } catch (e) { console.error('Dismiss edge failed', e); }
    setActionLoading(null);
  };

  const handleSaveType = async (edgeId) => {
    if (!editType.trim()) return;
    setActionLoading(edgeId);
    try {
      const updated = await updateGraphEdge(edgeId, { relationship_type: editType.trim(), review_status: 'confirmed' });
      setEdges(prev => prev.map(e => e.id === edgeId ? { ...e, ...updated } : e));
      setEditingId(null);
      setEditType('');
    } catch (e) { console.error('Update edge failed', e); }
    setActionLoading(null);
  };

  const statusColor = (status) => {
    if (status === 'confirmed') return C.success;
    if (status === 'dismissed') return C.danger;
    return C.warning;
  };

  const renderEdge = (edge) => {
    const isEditing = editingId === edge.id;
    const isLoading = actionLoading === edge.id;
    const isDismissed = edge.review_status === 'dismissed';

    return (
      <div key={edge.id} style={{
        padding: '8px 12px', marginBottom: 4, borderRadius: 4,
        background: isDismissed ? C.bg : C.card,
        border: '1px solid ' + C.border,
        opacity: isDismissed ? 0.5 : (isLoading ? 0.6 : 1),
        textDecoration: isDismissed ? 'line-through' : 'none',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ flex: 1, fontSize: 13 }}>
            <span style={{ color: C.accent, fontWeight: 500 }}>{edge.source_name || edge.source_entity_id}</span>
            {isEditing ? (
              <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', margin: '0 6px' }}>
                <span style={{ color: C.textDim }}>{'\u2192'}</span>
                <input value={editType}
                  onChange={e => setEditType(e.target.value)}
                  style={{
                    padding: '2px 6px', fontSize: 12, borderRadius: 3, width: 140,
                    background: C.bg, color: C.text, border: '1px solid ' + C.accent,
                    outline: 'none',
                  }}
                  placeholder="relationship type"
                  autoFocus
                  onKeyDown={e => { if (e.key === 'Enter') handleSaveType(edge.id); if (e.key === 'Escape') setEditingId(null); }}
                />
                <span style={{ color: C.textDim }}>{'\u2192'}</span>
              </span>
            ) : (
              <span style={{ color: C.textDim, margin: '0 6px' }}>{'\u2192'} {edge.relationship_type || 'related'} {'\u2192'}</span>
            )}
            <span style={{ color: C.purple, fontWeight: 500 }}>{edge.target_name || edge.target_entity_id}</span>
          </div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 3,
              background: statusColor(edge.review_status) + '22',
              color: statusColor(edge.review_status),
              fontWeight: 500,
            }}>{edge.review_status}</span>
            {edge.review_status === 'pending' && !isEditing && (
              <>
                <button onClick={() => handleConfirm(edge.id)} disabled={isLoading}
                  style={{ padding: '2px 8px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                    background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44' }}>
                  {'\u2713'}
                </button>
                <button onClick={() => { setEditingId(edge.id); setEditType(edge.relationship_type || ''); }} disabled={isLoading}
                  style={{ padding: '2px 8px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                    background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44' }}>
                  Edit
                </button>
                <button onClick={() => handleDismiss(edge.id)} disabled={isLoading}
                  style={{ padding: '2px 8px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                    background: C.danger + '22', color: C.danger, border: '1px solid ' + C.danger + '44' }}>
                  {'\u2717'}
                </button>
              </>
            )}
            {isEditing && (
              <>
                <button onClick={() => handleSaveType(edge.id)} disabled={isLoading || !editType.trim()}
                  style={{ padding: '2px 8px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                    background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
                    opacity: editType.trim() ? 1 : 0.4 }}>
                  Save
                </button>
                <button onClick={() => setEditingId(null)}
                  style={{ padding: '2px 8px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                    background: C.card, color: C.textDim, border: '1px solid ' + C.border }}>
                  Cancel
                </button>
              </>
            )}
            {edge.review_status === 'confirmed' && (
              <button onClick={() => handleDismiss(edge.id)} disabled={isLoading}
                style={{ padding: '2px 8px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                  background: C.danger + '22', color: C.danger, border: '1px solid ' + C.danger + '44' }}>
                {'\u2717'}
              </button>
            )}
            {edge.review_status === 'dismissed' && (
              <button onClick={() => handleConfirm(edge.id)} disabled={isLoading}
                style={{ padding: '2px 8px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
                  background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44' }}>
                Restore
              </button>
            )}
          </div>
        </div>
        {edge.strength != null && edge.review_status !== 'dismissed' && (
          <div style={{ fontSize: 10, color: C.textDim, marginTop: 2 }}>
            strength: {(edge.strength * 100).toFixed(0)}%
            {edge.notes ? ` \u2014 ${edge.notes}` : ''}
          </div>
        )}
      </div>
    );
  };

  if (edges.length === 0) {
    return (
      <div style={{
        ...cardStyle, marginBottom: 16,
        borderColor: C.border,
        background: C.card,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{'\u{1F517}'}</span>
          <span style={{ color: C.textDim, fontWeight: 500, fontSize: 13 }}>
            Graph Relationships {'\u2014'} No inferred edges for this conversation
          </span>
        </div>
      </div>
    );
  }

  if (!expanded) {
    return (
      <div style={{
        ...cardStyle, marginBottom: 16, cursor: 'pointer',
        borderColor: pending.length > 0 ? C.warning + '44' : C.success + '44',
        background: pending.length > 0 ? C.warning + '08' : C.success + '08',
      }} onClick={() => setExpanded(true)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{'\u{1F517}'}</span>
          <span style={{
            color: pending.length > 0 ? C.warning : C.success,
            fontWeight: 600, fontSize: 13,
          }}>
            {edges.length} graph edge{edges.length !== 1 ? 's' : ''}
            {pending.length > 0 ? ` (${pending.length} pending review)` : ' \u2014 all reviewed'}
          </span>
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto' }}>click to expand</span>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: pending.length > 0 ? C.warning + '44' : C.success + '44',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, cursor: 'pointer' }}
        onClick={() => setExpanded(false)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{'\u{1F517}'}</span>
          <span style={{ color: C.text, fontWeight: 600, fontSize: 13 }}>
            Graph Relationships ({edges.length})
          </span>
          {pending.length > 0 && (
            <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, fontWeight: 600,
              background: C.warning + '22', color: C.warning }}>{pending.length} pending</span>
          )}
        </div>
        <span style={{ color: C.textDim, fontSize: 11 }}>collapse</span>
      </div>
      {pending.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 600, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Pending Review</div>
          {pending.map(renderEdge)}
        </div>
      )}
      {confirmed.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 600, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Confirmed</div>
          {confirmed.map(renderEdge)}
        </div>
      )}
      {dismissed.length > 0 && (
        <div>
          <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 600, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Dismissed</div>
          {dismissed.map(renderEdge)}
        </div>
      )}
    </div>
  );
}

