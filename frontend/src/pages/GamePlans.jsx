import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { layout, colors } from '../styles';
import PageHeader from '../components/PageHeader';

export default function GamePlans() {
  const [intentions, setIntentions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.intentions()
      .then(data => setIntentions(Array.isArray(data) ? data : data.intentions || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <PageHeader title="Game Plans" subtitle="Meeting intentions and pre-meeting briefs" />

      <div style={layout.card}>
        {loading ? (
          <div style={{ color: colors.textDim, textAlign: 'center', padding: 40 }}>Loading...</div>
        ) : intentions.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <div style={{ color: colors.textDim, fontSize: 13 }}>
              No game plans yet. Create one before your next important meeting.
            </div>
            <div style={{ fontSize: 11, color: colors.textDim, marginTop: 8 }}>
              Game plans help you prepare goals, track commitments, and assess outcomes.
            </div>
          </div>
        ) : (
          <div>
            {intentions.map((intent, i) => {
              const goals = (() => {
                try { return JSON.parse(intent.goals); } catch { return []; }
              })();
              return (
                <div key={intent.id || i} style={{
                  padding: '16px 0',
                  borderBottom: i < intentions.length - 1 ? `1px solid ${colors.border}` : 'none',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>
                      {intent.target_contact_id || 'General'}
                    </div>
                    <span style={{ fontSize: 11, color: colors.textDim }}>
                      {intent.created_at?.slice(0, 10)}
                    </span>
                  </div>
                  {goals.length > 0 && (
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {goals.map((g, gi) => (
                        <li key={gi} style={{ fontSize: 12, color: colors.textMuted, marginBottom: 2 }}>{g}</li>
                      ))}
                    </ul>
                  )}
                  {intent.conversation_id && (
                    <div style={{ fontSize: 11, color: colors.success, marginTop: 6 }}>
                      Linked to conversation
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
