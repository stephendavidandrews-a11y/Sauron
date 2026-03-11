import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { layout, colors } from '../styles';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';

export default function Pipeline() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [ingestResult, setIngestResult] = useState(null);
  const [processResult, setProcessResult] = useState(null);
  const [ingesting, setIngesting] = useState(false);
  const [processing, setProcessing] = useState(false);

  const loadStatus = () => {
    api.pipelineStatus()
      .then(setStatus)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadStatus(); }, []);

  const handleIngest = async (source = null) => {
    setIngesting(true);
    setIngestResult(null);
    try {
      const result = await api.pipelineIngest(source);
      setIngestResult(result);
      loadStatus();
    } catch (e) {
      setIngestResult({ error: e.message });
    }
    setIngesting(false);
  };

  const handleProcessPending = async () => {
    setProcessing(true);
    setProcessResult(null);
    try {
      const result = await api.pipelineProcessPending();
      setProcessResult(result);
    } catch (e) {
      setProcessResult({ error: e.message });
    }
    setProcessing(false);
  };

  const convos = status?.conversations || {};
  const total = Object.values(convos).reduce((s, n) => s + n, 0);

  return (
    <div>
      <PageHeader title="Pipeline" subtitle="Audio ingestion, processing controls, and system status" />

      {/* Stats */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 24 }}>
        <StatCard label="Total Conversations" value={loading ? '...' : total} color={colors.accent} />
        <StatCard label="Pending" value={loading ? '...' : (convos.pending || 0)} color={convos.pending > 0 ? colors.warning : colors.success} />
        <StatCard label="Completed" value={loading ? '...' : (convos.completed || 0)} color={colors.success} />
        <StatCard label="Errors" value={loading ? '...' : (convos.error || 0)} color={(convos.error || 0) > 0 ? colors.danger : colors.textDim} />
      </div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 24 }}>
        <StatCard label="Episodes" value={loading ? '...' : (status?.total_episodes || 0)} color={colors.purple} />
        <StatCard label="Claims" value={loading ? '...' : (status?.total_claims || 0)} color={colors.accent} />
        <StatCard label="Beliefs" value={loading ? '...' : (status?.total_beliefs || 0)} color={colors.success} />
        <StatCard label="Embeddings" value={loading ? '...' : (status?.total_embeddings || 0)} color={colors.textMuted} />
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 24 }}>
        {/* Ingest */}
        <div style={{ ...layout.card, flex: 1 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Ingest Audio</h3>
          <p style={{ fontSize: 12, color: colors.textMuted, marginBottom: 16 }}>
            Scan inbox directories for new audio files and register them for processing.
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <ActionButton label="Ingest All" loading={ingesting} onClick={() => handleIngest()} />
            <ActionButton label="Pi" loading={ingesting} onClick={() => handleIngest('pi')} small />
            <ActionButton label="iPhone" loading={ingesting} onClick={() => handleIngest('iphone')} small />
            <ActionButton label="Plaud" loading={ingesting} onClick={() => handleIngest('plaud')} small />
            <ActionButton label="Email" loading={ingesting} onClick={() => handleIngest('email')} small />
          </div>
          {ingestResult && (
            <div style={{
              marginTop: 12, padding: 12, borderRadius: 6, fontSize: 12,
              background: ingestResult.error ? `${colors.danger}15` : `${colors.success}15`,
              color: ingestResult.error ? colors.danger : colors.success,
            }}>
              {ingestResult.error
                ? `Error: ${ingestResult.error}`
                : `Registered ${ingestResult.registered} files, skipped ${ingestResult.skipped}`}
            </div>
          )}
        </div>

        {/* Process */}
        <div style={{ ...layout.card, flex: 1 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Process</h3>
          <p style={{ fontSize: 12, color: colors.textMuted, marginBottom: 16 }}>
            Run the full pipeline on pending conversations (transcribe, diarize, extract, route, embed).
          </p>
          <ActionButton
            label={`Process ${convos.pending || 0} Pending`}
            loading={processing}
            onClick={handleProcessPending}
            disabled={!convos.pending}
          />
          {processResult && (
            <div style={{
              marginTop: 12, padding: 12, borderRadius: 6, fontSize: 12,
              background: processResult.error ? `${colors.danger}15` : `${colors.success}15`,
              color: processResult.error ? colors.danger : colors.success,
            }}>
              {processResult.error
                ? `Error: ${processResult.error}`
                : processResult.status === 'no_pending_conversations'
                  ? 'No pending conversations'
                  : `Processing started: ${processResult.pending_count} conversations`}
            </div>
          )}
        </div>
      </div>

      {/* Status breakdown */}
      {status && Object.keys(convos).length > 0 && (
        <div style={layout.card}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Status Breakdown</h3>
          {Object.entries(convos).map(([s, n]) => (
            <div key={s} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 0', borderBottom: `1px solid ${colors.border}`,
            }}>
              <StatusBadge status={s} />
              <span style={{ fontSize: 14, fontWeight: 600, color: colors.text }}>{n}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ActionButton({ label, loading, onClick, disabled, small }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      style={{
        padding: small ? '6px 12px' : '8px 16px',
        background: disabled ? colors.border : colors.accent,
        color: disabled ? colors.textDim : '#fff',
        border: 'none', borderRadius: 6,
        fontSize: small ? 12 : 13, cursor: disabled ? 'default' : 'pointer',
        fontWeight: 500, opacity: loading ? 0.7 : 1,
      }}
    >
      {loading ? 'Working...' : label}
    </button>
  );
}

function StatusBadge({ status }) {
  const c = {
    completed: colors.success, pending: colors.warning,
    processing: colors.accent, error: colors.danger,
  };
  return (
    <span style={{
      fontSize: 12, padding: '3px 10px', borderRadius: 4, fontWeight: 500,
      background: `${c[status] || colors.textDim}22`,
      color: c[status] || colors.textDim,
    }}>
      {status}
    </span>
  );
}
