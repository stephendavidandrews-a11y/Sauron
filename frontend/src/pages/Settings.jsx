import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { layout, colors } from '../styles';
import PageHeader from '../components/PageHeader';

export default function Settings() {
  const [health, setHealth] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [amendments, setAmendments] = useState([]);

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.profiles().then(data => setProfiles(Array.isArray(data) ? data : data.profiles || [])).catch(() => {});
    api.amendments().then(data => setAmendments(Array.isArray(data) ? data : data.amendments || [])).catch(() => {});
  }, []);

  return (
    <div>
      <PageHeader title="Settings" subtitle="System configuration and status" />

      {/* System status */}
      <div style={{ ...layout.card, marginBottom: 16 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>System Status</h3>
        <Row label="Version" value={health?.version || '—'} />
        <Row label="Status" value={health?.status || '—'} color={health?.status === 'operational' ? colors.success : colors.warning} />
        <Row label="Scheduler" value={health?.scheduler_active ? 'Active' : 'Inactive'} color={health?.scheduler_active ? colors.success : colors.textDim} />
        <Row label="Total Conversations" value={health?.conversations?.total ?? '—'} />
        <Row label="Pending" value={health?.conversations?.pending ?? '—'} />
      </div>

      {/* Voice profiles */}
      <div style={{ ...layout.card, marginBottom: 16 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
          Voice Profiles ({profiles.length})
        </h3>
        {profiles.length === 0 ? (
          <div style={{ fontSize: 12, color: colors.textDim }}>No voice profiles enrolled yet.</div>
        ) : (
          profiles.map((p, i) => (
            <div key={p.id || i} style={{
              padding: '8px 0',
              borderBottom: i < profiles.length - 1 ? `1px solid ${colors.border}` : 'none',
              fontSize: 13,
            }}>
              {p.label || p.contact_id || p.id}
            </div>
          ))
        )}
      </div>

      {/* Learning amendments */}
      <div style={layout.card}>
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
          Learning Amendments ({amendments.length})
        </h3>
        {amendments.length === 0 ? (
          <div style={{ fontSize: 12, color: colors.textDim }}>
            No prompt amendments generated yet. Corrections will automatically improve extraction over time.
          </div>
        ) : (
          amendments.map((a, i) => (
            <div key={a.id || i} style={{
              padding: '10px 0',
              borderBottom: i < amendments.length - 1 ? `1px solid ${colors.border}` : 'none',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>{a.version || `v${i + 1}`}</span>
                <span style={{ fontSize: 11, color: a.active ? colors.success : colors.textDim }}>
                  {a.active ? 'Active' : 'Superseded'}
                </span>
              </div>
              <div style={{ fontSize: 12, color: colors.textMuted }}>
                {a.amendment_text?.slice(0, 150) || '—'}
                {a.amendment_text?.length > 150 ? '...' : ''}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function Row({ label, value, color }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between',
      padding: '6px 0', borderBottom: `1px solid ${colors.border}`,
      fontSize: 13,
    }}>
      <span style={{ color: colors.textMuted }}>{label}</span>
      <span style={{ color: color || colors.text, fontWeight: 500 }}>{value}</span>
    </div>
  );
}
