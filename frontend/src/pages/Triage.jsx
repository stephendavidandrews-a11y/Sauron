import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { layout, colors } from '../styles';
import PageHeader from '../components/PageHeader';

export default function Triage() {
  const [convos, setConvos] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.conversations(100, 0)
      .then(data => {
        const all = Array.isArray(data) ? data : data.conversations || [];
        setConvos(all.filter(c => c.processing_status === 'pending' || c.processing_status === 'error' || c.processing_status === 'triage_rejected'));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <PageHeader title="Triage" subtitle="Pending and errored conversations requiring attention" />

      <div style={layout.card}>
        {loading ? (
          <div style={{ color: colors.textDim, textAlign: 'center', padding: 40 }}>Loading...</div>
        ) : convos.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>&#10003;</div>
            <div style={{ color: colors.success, fontSize: 14 }}>All clear</div>
            <div style={{ color: colors.textDim, fontSize: 12, marginTop: 4 }}>
              No conversations need attention.
            </div>
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 12, color: colors.textDim, marginBottom: 12 }}>
              {convos.length} item{convos.length !== 1 ? 's' : ''} requiring attention
            </div>
            {convos.map(c => (
              <div key={c.id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '12px 0', borderBottom: `1px solid ${colors.border}`,
              }}>
                <div>
                  <div style={{ fontSize: 13 }}>{c.manual_note || c.source_type || c.id.slice(0, 8)}</div>
                  <div style={{ fontSize: 11, color: colors.textDim, marginTop: 2 }}>
                    {c.source_type} · {c.created_at?.slice(0, 10)}
                  </div>
                </div>
                <span style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 4, fontWeight: 500,
                  background: c.processing_status === 'error' ? `${colors.danger}22` : `${colors.warning}22`,
                  color: c.processing_status === 'error' ? colors.danger : colors.warning,
                }}>
                  {c.processing_status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
