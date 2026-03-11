import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { layout, colors } from '../styles';
import PageHeader from '../components/PageHeader';

export default function Conversations() {
  const [convos, setConvos] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.conversations(100, 0)
      .then(data => setConvos(Array.isArray(data) ? data : data.conversations || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <PageHeader title="Conversations" subtitle={`${convos.length} recorded conversations`} />

      <div style={layout.card}>
        {loading ? (
          <div style={{ color: colors.textDim, textAlign: 'center', padding: 40 }}>Loading...</div>
        ) : convos.length === 0 ? (
          <div style={{ color: colors.textDim, textAlign: 'center', padding: 40 }}>
            No conversations found. Use the <Link to="/pipeline" style={{ color: colors.accent }}>Pipeline</Link> page to ingest audio files.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                {['Date', 'Source', 'Duration', 'Status'].map(h => (
                  <th key={h} style={{
                    textAlign: 'left', padding: '8px 12px', fontSize: 11,
                    color: colors.textDim, fontWeight: 500, textTransform: 'uppercase',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {convos.map(c => (
                <tr
                  key={c.id}
                  style={{ borderBottom: `1px solid ${colors.border}`, cursor: 'pointer' }}
                  onMouseEnter={e => e.currentTarget.style.background = colors.cardHover}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '10px 12px', fontSize: 13 }}>
                    <Link to={`/conversations/${c.id}`} style={{ color: colors.text, textDecoration: 'none' }}>
                      {(c.captured_at || c.created_at)?.slice(0, 10) || '\u2014'}
                    </Link>
                  </td>
                  <td style={{ padding: '10px 12px', fontSize: 13, color: colors.textMuted }}>
                    {c.source || c.source_type || '\u2014'}
                  </td>
                  <td style={{ padding: '10px 12px', fontSize: 13, color: colors.textMuted }}>
                    {c.duration_seconds ? `${Math.round(c.duration_seconds / 60)}m` : '\u2014'}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <StatusBadge status={c.processing_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const c = {
    completed: colors.success, pending: colors.warning,
    processing: colors.accent, error: colors.danger,
  };
  return (
    <span style={{
      fontSize: 11, padding: '3px 8px', borderRadius: 4,
      background: `${c[status] || colors.textDim}22`,
      color: c[status] || colors.textDim, fontWeight: 500,
    }}>
      {status || 'unknown'}
    </span>
  );
}
