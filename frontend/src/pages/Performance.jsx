import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { layout, colors } from '../styles';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';

export default function Performance() {
  const [perf, setPerf] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.performance()
      .then(setPerf)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <PageHeader title="Performance" subtitle="Pipeline processing statistics" />

      {loading ? (
        <div style={{ color: colors.textDim, padding: 40, textAlign: 'center' }}>Loading...</div>
      ) : !perf ? (
        <div style={{ ...layout.card, textAlign: 'center', padding: 40 }}>
          <div style={{ color: colors.textDim }}>Performance data not available yet.</div>
        </div>
      ) : (
        <div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 24 }}>
            <StatCard
              label="Total Processed"
              value={perf.total_processed ?? perf.conversations_processed ?? '—'}
              color={colors.accent}
            />
            <StatCard
              label="Avg Processing Time"
              value={perf.avg_processing_time ? `${Number(perf.avg_processing_time).toFixed(1)}s` : '—'}
              color={colors.success}
            />
            <StatCard
              label="Error Rate"
              value={perf.error_rate != null ? `${(perf.error_rate * 100).toFixed(1)}%` : '—'}
              color={perf.error_rate > 0.1 ? colors.danger : colors.success}
            />
          </div>

          <div style={layout.card}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Raw Data</h3>
            <pre style={{
              fontSize: 12, color: colors.textMuted, whiteSpace: 'pre-wrap', lineHeight: 1.5,
            }}>
              {JSON.stringify(perf, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
