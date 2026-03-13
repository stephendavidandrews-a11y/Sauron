import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { layout, colors } from '../styles';
import PageHeader from '../components/PageHeader';
import RenamePreview from '../components/RenamePreview';

export default function People() {
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(true);
  const [renameContact, setRenameContact] = useState(null);

  const loadGraph = () => {
    api.graph()
      .then(setGraph)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadGraph(); }, []);

  const contacts = graph?.contacts || graph?.nodes || [];

  return (
    <div>
      <PageHeader title="People" subtitle="Contacts and relationship graph" />

      <div style={layout.card}>
        {loading ? (
          <div style={{ color: colors.textDim, textAlign: 'center', padding: 40 }}>Loading...</div>
        ) : contacts.length === 0 ? (
          <div style={{ color: colors.textDim, textAlign: 'center', padding: 40 }}>
            No contacts found. People will appear here as conversations are processed.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {contacts.map((c, i) => (
              <div key={c.id || i} style={{
                padding: 16, borderRadius: 6,
                border: `1px solid ${colors.border}`,
                background: colors.bg,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
                    {c.canonical_name || c.display_name || c.id}
                  </div>
                  <button
                    onClick={() => setRenameContact(c)}
                    title="Rename contact and propagate to all records"
                    style={{
                      background: 'none', border: 'none', color: colors.textDim,
                      fontSize: 11, cursor: 'pointer', padding: '2px 6px',
                      borderRadius: 4, flexShrink: 0,
                    }}
                    onMouseEnter={e => { e.target.style.color = colors.accent; e.target.style.background = colors.accent + '15'; }}
                    onMouseLeave={e => { e.target.style.color = colors.textDim; e.target.style.background = 'none'; }}
                  >
                    Rename
                  </button>
                </div>
                {c.organization && (
                  <div style={{ fontSize: 12, color: colors.textMuted }}>{c.organization}</div>
                )}
                {c.email && (
                  <div style={{ fontSize: 11, color: colors.textDim, marginTop: 4 }}>{c.email}</div>
                )}
                {c.conversation_count != null && (
                  <div style={{ fontSize: 11, color: colors.accent, marginTop: 6 }}>
                    {c.conversation_count} conversation{c.conversation_count !== 1 ? 's' : ''}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {renameContact && (
        <RenamePreview
          contact={renameContact}
          onClose={() => setRenameContact(null)}
          onApplied={() => { setRenameContact(null); loadGraph(); }}
        />
      )}
    </div>
  );
}
