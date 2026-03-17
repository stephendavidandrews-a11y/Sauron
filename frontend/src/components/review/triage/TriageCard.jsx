import { useState } from 'react';
import { api } from '../../../api';
import { C } from "../../../utils/colors";
import { relativeTime } from "../../../utils/time";
import { StatusDot } from '../StatusDot';

export function TriageCard({ convo, onPromote, onArchive, onDiscard }) {
  const [expanded, setExpanded] = useState(false);
  const [triageData, setTriageData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);

  const handleExpand = async () => {
    if (!expanded && !triageData) {
      setLoading(true);
      try {
        const data = await api.triageData(convo.id);
        setTriageData(data);
      } catch (e) {
        console.error('Failed to load triage data:', e);
      }
      setLoading(false);
    }
    setExpanded(!expanded);
  };

  const handlePromote = async () => {
    setActing(true);
    try {
      await onPromote(convo.id);
    } finally {
      setActing(false);
    }
  };

  const handleArchive = async () => {
    setActing(true);
    try {
      await onArchive(convo.id);
    } finally {
      setActing(false);
    }
  };

  const handleDiscard = async () => {
    if (!window.confirm('Discard this conversation? It will be permanently removed from review.')) return;
    setActing(true);
    try {
      if (onDiscard) await onDiscard(convo.id);
    } catch (e) { console.error('Discard failed', e); }
    setActing(false);
  };

  return (
    <div style={{ borderBottom: `1px solid ${C.border}` }}>
      <div
        onClick={handleExpand}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <StatusDot color={C.warning} />
          <span style={{ color: C.text, fontSize: 14 }}>
            {convo.manual_note || convo.title || (convo.source + " capture")}
            {convo.duration_seconds ? ` \u2014 ${Math.round(convo.duration_seconds / 60)}min` : ''}
          </span>
          <span style={{ color: C.textDim, fontSize: 12 }}>triaged low-value</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: C.textDim, fontSize: 12 }}>{relativeTime(convo.captured_at || convo.created_at)}</span>
          <span style={{ color: C.textDim, fontSize: 14 }}>{expanded ? '\u25B2' : '\u25BC'}</span>
        </div>
      </div>

      {expanded && (
        <div style={{ padding: '0 12px 16px 32px' }}>
          {loading ? (
            <div style={{ color: C.textDim, fontSize: 13 }}>Loading triage data...</div>
          ) : triageData ? (
            <div>
              {triageData.triage?.overall_value && (
                <div style={{ fontSize: 13, color: C.textMuted, marginBottom: 8 }}>
                  <strong>Value:</strong> {triageData.triage.overall_value}
                  {triageData.triage.value_reasoning && (
                    <span style={{ color: C.textDim }}> &mdash; {triageData.triage.value_reasoning}</span>
                  )}
                </div>
              )}
              {triageData.triage?.topic_tags && (
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
                  {triageData.triage.topic_tags.map((t, i) => (
                    <span key={i} style={{
                      fontSize: 11, padding: '2px 6px', borderRadius: 4,
                      background: C.border, color: C.textMuted,
                    }}>{t}</span>
                  ))}
                </div>
              )}
              {triageData.triage?.context_classification && (
                <div style={{ fontSize: 13, color: C.textDim, marginBottom: 8 }}>
                  Context: {triageData.triage.context_classification}
                </div>
              )}
              {triageData.episodes && triageData.episodes.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, color: C.textDim, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Episodes ({triageData.episodes.length})
                  </div>
                  {triageData.episodes.slice(0, 5).map((ep, i) => (
                    <div key={i} style={{ fontSize: 12, color: C.textMuted, padding: '2px 0' }}>
                      {ep.summary || ep.title || `Episode ${i + 1}`}
                    </div>
                  ))}
                  {triageData.episodes.length > 5 && (
                    <div style={{ fontSize: 11, color: C.textDim }}>...and {triageData.episodes.length - 5} more</div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: C.textDim }}>No triage data available</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              onClick={handlePromote} disabled={acting}
              style={{
                padding: '6px 14px', background: C.accent, color: '#fff', border: 'none',
                borderRadius: 6, fontSize: 12, cursor: 'pointer', opacity: acting ? 0.7 : 1,
              }}
            >
              {acting ? 'Processing...' : 'Promote to Full Extraction'}
            </button>
            <button
              onClick={handleArchive} disabled={acting}
              style={{
                padding: '6px 14px', background: 'transparent', color: C.textDim,
                border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 12, cursor: 'pointer',
                opacity: acting ? 0.7 : 1,
              }}
            >
              Archive as Low Value
            </button>
            <button
              onClick={handleDiscard} disabled={acting}
              style={{
                padding: '6px 14px', background: 'transparent', color: C.danger,
                border: '1px solid ' + C.danger + '33', borderRadius: 6, fontSize: 12,
                cursor: 'pointer', opacity: acting ? 0.7 : 1,
              }}
            >
              Discard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
