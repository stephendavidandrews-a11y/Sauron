import { useState, useEffect } from 'react';
import { api } from '../../../api';
import { C } from "../../../utils/colors";

export function DuplicateContactBanner() {
  const [dupData, setDupData] = useState(null);
  const [resolving, setResolving] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    api.checkDuplicateContacts()
      .then(data => {
        if (data && data.status === 'duplicates_found') setDupData(data);
      })
      .catch(() => {});
  }, []);

  if (!dupData || dismissed) return null;

  const handleResolve = async () => {
    const groups = dupData.groups.map(g => g.contacts[0]?.canonical_name + ' (' + g.sauron_count + ' rows)').join(', ');
    if (!window.confirm('Merge duplicate contacts?\n\nGroups: ' + groups + '\n\nThis cannot be undone.')) return;
    setResolving(true);
    try {
      const result = await api.resolveDuplicateContacts();
      if (result && result.resolved > 0) {
        setDupData(null);
      }
    } catch (e) {
      console.error('Failed to resolve duplicates:', e);
    }
    setResolving(false);
  };

  const hasNetWarnings = dupData.networking_warnings && dupData.networking_warnings.length > 0;

  return (
    <div style={{
      background: C.warning + '15', border: `1px solid ${C.warning}40`, borderRadius: 8,
      padding: '12px 16px', marginBottom: 16, fontSize: 13,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>{'\u26A0'}</span>
          <span style={{ color: C.warning, fontWeight: 600 }}>
            {dupData.duplicate_count} duplicate contact group{dupData.duplicate_count > 1 ? 's' : ''} detected
          </span>
          <span style={{ color: C.textDim }}>
            ({dupData.total_extra_rows} extra row{dupData.total_extra_rows > 1 ? 's' : ''} in contacts)
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleResolve} disabled={resolving}
            style={{
              fontSize: 11, padding: '4px 12px', borderRadius: 4, cursor: 'pointer',
              background: C.accent + '22', color: C.accent, border: `1px solid ${C.accent}44`,
              fontWeight: 600,
            }}>
            {resolving ? 'Resolving...' : 'Auto-resolve'}
          </button>
          <button onClick={() => setDismissed(true)}
            style={{
              fontSize: 11, padding: '4px 8px', borderRadius: 4, cursor: 'pointer',
              background: 'transparent', color: C.textDim, border: `1px solid ${C.border}`,
            }}>
            Dismiss
          </button>
        </div>
      </div>
      {hasNetWarnings && (
        <div style={{ marginTop: 8, padding: '8px 12px', background: C.error + '12',
          borderRadius: 4, border: `1px solid ${C.error}30` }}>
          <span style={{ color: C.error, fontWeight: 600, fontSize: 12 }}>
            {'\u26D4'} Networking app warnings:
          </span>
          {dupData.networking_warnings.map((w, i) => (
            <div key={i} style={{ color: C.textDim, fontSize: 12, marginTop: 4 }}>
              {w.warning}
            </div>
          ))}
        </div>
      )}
      <div style={{ marginTop: 8, fontSize: 12, color: C.textDim }}>
        {dupData.groups.map(g => (
          <span key={g.networking_app_contact_id} style={{ marginRight: 12 }}>
            {g.contacts[0]?.canonical_name} ({g.sauron_count} rows)
            {g.networking_app_status?.exists ? ' \u2713' : ' \u2717'}
          </span>
        ))}
      </div>
    </div>
  );
}
