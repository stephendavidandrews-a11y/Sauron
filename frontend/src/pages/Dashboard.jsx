import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { layout, colors } from '../styles';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';

export default function Dashboard() {
  const [health, setHealth] = useState(null);
  const [pipeline, setPipeline] = useState(null);
  const [convos, setConvos] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.health().then(setHealth).catch(e => setError(e.message));
    api.pipelineStatus().then(setPipeline).catch(() => {});
    api.conversations(5, 0).then(data => {
      setConvos(Array.isArray(data) ? data : data.conversations || []);
    }).catch(() => {});
  }, []);

  const convCounts = pipeline?.conversations || {};
  const total = Object.values(convCounts).reduce((s, n) => s + n, 0);

  return (
    <div>
      <PageHeader title="Dashboard" subtitle="System overview and recent activity" />

      {error && (
        <div style={{ ...layout.card, borderColor: colors.danger, marginBottom: 16 }}>
          <span style={{ color: colors.danger }}>Connection error: {error}</span>
        </div>
      )}

      {/* Primary stats */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 16 }}>
        <StatCard
          label="Conversations"
          value={total || health?.conversations?.total || '\u2014'}
          color={colors.accent}
        />
        <StatCard
          label="Pending"
          value={convCounts.pending ?? health?.conversations?.pending ?? '\u2014'}
          color={(convCounts.pending || 0) > 0 ? colors.warning : colors.success}
        />
        <StatCard
          label="Voice Profiles"
          value={health?.voice_profiles ?? '\u2014'}
          color={colors.purple}
        />
        <StatCard
          label="Scheduler"
          value={health?.scheduler_active ? 'Active' : 'Off'}
          color={health?.scheduler_active ? colors.success : colors.textDim}
        />
      </div>

      {/* v6 intelligence stats */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 24 }}>
        <StatCard label="Episodes" value={pipeline?.total_episodes ?? '\u2014'} color={colors.purple} sub="Event segments" />
        <StatCard label="Claims" value={pipeline?.total_claims ?? '\u2014'} color={colors.accent} sub="Extracted facts" />
        <StatCard label="Beliefs" value={pipeline?.total_beliefs ?? '\u2014'} color={colors.success} sub="Derived truths" />
        <StatCard label="Embeddings" value={pipeline?.total_embeddings ?? '\u2014'} color={colors.textMuted} sub="Searchable vectors" />
      </div>

      {/* Recent conversations */}
      <div style={layout.card}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: 16,
        }}>
          <h2 style={{ fontSize: 16, fontWeight: 600 }}>Recent Conversations</h2>
          <Link to="/conversations" style={{ fontSize: 13, color: colors.accent, textDecoration: 'none' }}>
            View all
          </Link>
        </div>

        {convos.length === 0 ? (
          <div style={{ color: colors.textDim, fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
            No conversations yet. Drop audio files into inbox directories or use the{' '}
            <Link to="/pipeline" style={{ color: colors.accent }}>Pipeline</Link> page to ingest.
          </div>
        ) : (
          <div>
            {convos.map(c => (
              <Link
                key={c.id}
                to={`/conversations/${c.id}`}
                style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '12px 0', borderBottom: `1px solid ${colors.border}`,
                  textDecoration: 'none', color: colors.text,
                }}
              >
                <div>
                  <div style={{ fontSize: 14 }}>{c.manual_note || c.source || c.source_type || 'Untitled'}</div>
                  <div style={{ fontSize: 11, color: colors.textDim, marginTop: 2 }}>
                    {c.source || c.source_type} {'\u00B7'} {(c.captured_at || c.created_at)?.slice(0, 10)}
                    {c.duration_seconds ? ` \u00B7 ${Math.round(c.duration_seconds / 60)}m` : ''}
                  </div>
                </div>
                <StatusBadge status={c.processing_status} />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const sc = {
    completed: colors.success, pending: colors.warning,
    processing: colors.accent, error: colors.danger,
  };
  return (
    <span style={{
      fontSize: 11, padding: '3px 8px', borderRadius: 4,
      background: `${sc[status] || colors.textDim}22`,
      color: sc[status] || colors.textDim, fontWeight: 500,
    }}>
      {status || 'unknown'}
    </span>
  );
}
