import { useState, useEffect } from 'react';
import { api } from '../../../api';
import { C, cardStyle } from '../styles';

const OBJECT_TYPE_LABELS = {
  interactions: 'Interactions',
  commitments: 'Commitments',
  scheduling_leads: 'Scheduling Leads',
  standing_offers: 'Standing Offers',
  signals: 'Signals',
  life_events: 'Life Events',
  relationships: 'Relationships',
  affiliations: 'Affiliations',
  provenance: 'Provenance',
  profile_signals: 'Profile Signals',
  participants: 'Participants',
  contact_patches: 'Contact Updates',
  graph_edges: 'Graph Edges',
};

export function RoutingPreview({ conversationId, refreshKey }) {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [expandedTypes, setExpandedTypes] = useState({});

  useEffect(() => {
    setLoading(true);
    api.routingPreview(conversationId)
      .then(d => {
        setPreview(d);
        // Auto-expand if there are blocked items
        if (d.blocked_count > 0) setExpanded(true);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conversationId, refreshKey]);

  if (loading || !preview) return null;
  if (preview.ready_count === 0 && preview.blocked_count === 0) return null;

  const totalObjects = preview.ready_count + preview.blocked_count + (preview.skipped_count || 0);
  const allReady = preview.blocked_count === 0 && (preview.skipped_count || 0) === 0;
  const objectTypes = Object.keys(preview.objects || {});

  const toggleType = (type) => {
    setExpandedTypes(prev => ({ ...prev, [type]: !prev[type] }));
  };

  // Collapsed state: all ready
  if (allReady && !expanded) {
    return (
      <div style={{
        ...cardStyle, marginBottom: 16, cursor: 'pointer',
        borderColor: C.success + '33',
        background: C.success + '06',
      }} onClick={() => setExpanded(true)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{'\u{1F4E6}'}</span>
          <span style={{ color: C.success, fontWeight: 600, fontSize: 13 }}>
            {'\u2705'} {totalObjects} object{totalObjects !== 1 ? 's' : ''} ready to route
          </span>
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto' }}>click to expand</span>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: allReady ? C.success + '33' : C.border,
      background: allReady ? C.success + '06' : C.card,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 14 }}>{'\u{1F4E6}'}</span>
        <span style={{ fontWeight: 600, fontSize: 14, color: C.text }}>
          Routing Preview
        </span>
        <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 3, background: C.success + '22', color: C.success }}>
          {preview.ready_count} ready
        </span>
        {preview.blocked_count > 0 && (
          <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 3, background: C.danger + '22', color: C.danger }}>
            {preview.blocked_count} blocked
          </span>
        )}
        {(preview.skipped_count || 0) > 0 && (
          <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 3, background: C.warning + '22', color: C.warning }}>
            {preview.skipped_count} skipped
          </span>
        )}
        {allReady && (
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto', cursor: 'pointer' }}
            onClick={() => setExpanded(false)}>
            collapse
          </span>
        )}
      </div>

      {objectTypes.map(type => {
        const items = preview.objects[type];
        const label = OBJECT_TYPE_LABELS[type] || type.replace(/_/g, ' ');
        const readyCount = items.filter(i => i.status === 'ready').length;
        const blockedCount = items.filter(i => i.status === 'blocked').length;
        const skippedCount = items.filter(i => i.status === 'skipped').length;
        const isTypeExpanded = expandedTypes[type] !== undefined ? expandedTypes[type] : blockedCount > 0;

        return (
          <div key={type} style={{ marginBottom: 8 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '6px 0',
              cursor: 'pointer', userSelect: 'none',
            }} onClick={() => toggleType(type)}>
              <span style={{ fontSize: 11, color: C.textDim }}>{isTypeExpanded ? '\u25BC' : '\u25B6'}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.text, textTransform: 'capitalize' }}>
                {label}
              </span>
              <span style={{ fontSize: 11, color: C.textDim }}>({items.length})</span>
              {blockedCount > 0 && (
                <span style={{ fontSize: 10, padding: '0 5px', borderRadius: 3, background: C.danger + '22', color: C.danger }}>
                  {blockedCount} blocked
                </span>
              )}
            </div>

            {isTypeExpanded && (
              <div style={{ paddingLeft: 16 }}>
                {items.map((item, idx) => {
                  const isBlocked = item.status === 'blocked';
                  const isSkipped = item.status === 'skipped';
                  return (
                    <div key={idx} style={{
                      display: 'flex', alignItems: 'flex-start', gap: 6, padding: '4px 0',
                      fontSize: 12, opacity: isSkipped ? 0.5 : 1,
                    }}>
                      <span style={{ flexShrink: 0, marginTop: 1 }}>
                        {isBlocked ? '\u{1F534}' : isSkipped ? '\u23ED\uFE0F' : '\u2705'}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ color: isBlocked ? C.text : C.textMuted }}>
                          {item.summary || '(no summary)'}
                        </span>
                        {isBlocked && item.blocker && (
                          <div style={{ fontSize: 11, color: C.danger, marginTop: 2 }}>
                            {'\u2514'} {item.blocker}
                          </div>
                        )}
                        {/* Show people chips */}
                        {item.people && item.people.length > 0 && (
                          <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginTop: 3 }}>
                            {item.people.map((p, pi) => (
                              <span key={pi} style={{
                                fontSize: 10, padding: '1px 5px', borderRadius: 3,
                                background: p.skipped ? (C.warning + '15') : p.resolved ? (C.success + '15') : (C.danger + '15'),
                                color: p.skipped ? C.warning : p.resolved ? C.success : C.danger,
                              }}>
                                {p.skipped ? '\u23ED ' : p.resolved ? '\u2713 ' : '\u2717 '}
                                {p.canonical_name || p.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}


