import { useState, useEffect } from 'react';
import { api } from '../../../api';
import { C, cardStyle } from '../styles';

export function ObjectsReviewBanner({ conversationId, onResolved }) {
  const [entities, setEntities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);

  const typeConfig = {
    organization: { icon: '\u{1F3E2}', color: '#f59e0b', label: 'Org' },
    legislation: { icon: '\u{1F4DC}', color: '#8b5cf6', label: 'Law' },
    topic: { icon: '\u{1F3F7}', color: '#06b6d4', label: 'Topic' },
  };

  const fetchEntities = useCallback(() => {
    api.conversationEntities(conversationId)
      .then(data => setEntities(data || []))
      .catch(() => setEntities([]))
      .finally(() => setLoading(false));
  }, [conversationId]);

  useEffect(() => { fetchEntities(); }, [fetchEntities]);

  if (loading || entities.length === 0) return null;

  const provisional = entities.filter(e => !e.is_confirmed);
  const confirmed = entities.filter(e => e.is_confirmed);
  const allConfirmed = provisional.length === 0;

  const handleConfirm = async (entity) => {
    setActionLoading(entity.id);
    try {
      await api.confirmEntity(entity.id);
      fetchEntities();
      if (onResolved) onResolved();
    } catch (e) { console.error('Confirm entity failed', e); }
    setActionLoading(null);
  };

  const handleDismiss = async (entity) => {
    setActionLoading(entity.id);
    try {
      await api.dismissEntity(entity.id);
      fetchEntities();
      if (onResolved) onResolved();
    } catch (e) { console.error('Dismiss entity failed', e); }
    setActionLoading(null);
  };

  // Collapsed state when all confirmed
  if (allConfirmed && !expanded) {
    return (
      <div style={{
        ...cardStyle, marginBottom: 16, cursor: 'pointer',
        borderColor: '#10b98144', background: '#10b98108',
      }} onClick={() => setExpanded(true)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{'\u{1F4CC}'}</span>
          <span style={{ color: C.success, fontWeight: 600, fontSize: 13 }}>
            {entities.length} entit{entities.length === 1 ? 'y' : 'ies'} {'\u2014'} all confirmed {'\u2705'}
          </span>
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto' }}>click to expand</span>
        </div>
      </div>
    );
  }

  const bannerColor = allConfirmed ? C.success : C.warning;

  const renderEntityRow = (entity) => {
    const tc = typeConfig[entity.entity_type] || { icon: '\u{1F4CC}', color: C.textMuted, label: entity.entity_type };
    const isLoading = actionLoading === entity.id;
    return (
      <div key={entity.id} style={{
        padding: entity.is_confirmed ? '6px 12px' : '10px 12px', marginBottom: 6,
        background: entity.is_confirmed ? 'transparent' : C.card,
        borderRadius: 6,
        border: entity.is_confirmed ? 'none' : `1px solid ${C.border}`,
        opacity: isLoading ? 0.6 : 1,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
            background: entity.is_confirmed ? C.success : C.warning, flexShrink: 0
          }} />
          <span style={{ fontSize: 14 }}>{tc.icon}</span>
          <span style={{ color: C.text, fontWeight: 500, fontSize: 13 }}>
            {entity.canonical_name}
          </span>
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 3,
            background: `${tc.color}22`, color: tc.color,
          }}>{tc.label}</span>
          {entity.observation_count > 1 && (
            <span style={{ fontSize: 10, color: C.textDim }}>
              {entity.observation_count}x seen
            </span>
          )}
          {entity.description && (
            <span style={{ fontSize: 11, color: C.textDim, flex: 1, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={entity.description}>
              {'\u2014'} {entity.description}
            </span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
            {!entity.is_confirmed && (
              <>
                <button onClick={() => handleConfirm(entity)} disabled={isLoading}
                  style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3,
                    border: `1px solid ${C.success}44`, background: 'transparent',
                    color: C.success, cursor: 'pointer' }}>{'\u2713'}</button>
                <button onClick={() => handleDismiss(entity)} disabled={isLoading}
                  style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3,
                    border: `1px solid ${C.danger}44`, background: 'transparent',
                    color: C.danger, cursor: 'pointer' }}>{'\u2715'}</button>
              </>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: `${bannerColor}44`, background: `${bannerColor}08`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: provisional.length > 0 ? 12 : 0,
        cursor: 'pointer' }} onClick={() => setExpanded(!expanded)}>
        <span style={{ fontSize: 14 }}>{'\u{1F4CC}'}</span>
        <span style={{ color: bannerColor, fontWeight: 600, fontSize: 13 }}>
          {entities.length} entit{entities.length === 1 ? 'y' : 'ies'}
          {provisional.length > 0 && ` (${provisional.length} provisional)`}
        </span>
        <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto' }}>
          {expanded ? 'collapse' : 'expand'}
        </span>
      </div>
      {(expanded || provisional.length > 0) && (
        <div>
          {provisional.map(renderEntityRow)}
          {expanded && confirmed.map(renderEntityRow)}
        </div>
      )}
    </div>
  );
}

