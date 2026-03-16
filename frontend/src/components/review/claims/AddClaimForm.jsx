import { useState } from 'react';
import { api } from '../../../api';
import { C, claimTypeColors } from '../styles';

export function AddClaimForm({ conversationId, episodeId, contacts, onCreated, onCancel }) {
  const [claimType, setClaimType] = useState('fact');
  const [claimText, setClaimText] = useState('');
  const [subjectName, setSubjectName] = useState('');
  const [subjectEntityId, setSubjectEntityId] = useState(null);
  const [evidenceQuote, setEvidenceQuote] = useState('');
  const [firmness, setFirmness] = useState('');
  const [direction, setDirection] = useState('');
  const [saving, setSaving] = useState(false);
  const [contactSearch, setContactSearch] = useState('');

  const filteredContacts = contacts.filter(c =>
    c.display_name?.toLowerCase().includes(contactSearch.toLowerCase())
  ).slice(0, 8);

  const handleSubmit = async () => {
    if (!claimText.trim()) return;
    setSaving(true);
    try {
      const data = {
        conversation_id: conversationId,
        episode_id: episodeId || null,
        claim_type: claimType,
        claim_text: claimText.trim(),
        subject_name: subjectName || null,
        subject_entity_id: subjectEntityId || null,
        evidence_quote: evidenceQuote || null,
      };
      if (claimType === 'commitment') {
        data.firmness = firmness || null;
        data.direction = direction || null;
      }
      const result = await api.addClaim(data);
      if (result.claim) onCreated(result.claim);
      onCancel();
    } catch (e) { console.error('Add claim failed', e); }
    setSaving(false);
  };

  const S = {
    label: { fontSize: 11, color: C.textMuted, marginBottom: 2, display: 'block' },
    select: { fontSize: 12, padding: '4px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%' },
    input: { fontSize: 12, padding: '4px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%' },
    textarea: { fontSize: 12, padding: '4px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%', resize: 'vertical' },
  };

  return (
    <div style={{ padding: '12px', borderRadius: 6, background: C.accent + '08',
      border: `1px solid ${C.accent}40`, marginTop: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.accent, marginBottom: 10 }}>
        Add New Claim
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
        <div style={{ flex: '0 0 140px' }}>
          <label style={S.label}>Type</label>
          <select style={S.select} value={claimType} onChange={e => setClaimType(e.target.value)}>
            <option value="fact">fact</option>
            <option value="position">position</option>
            <option value="commitment">commitment</option>
            <option value="preference">preference</option>
            <option value="relationship">relationship</option>
            <option value="observation">observation</option>
            <option value="tactical">tactical</option>
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={S.label}>Subject</label>
          <div style={{ position: 'relative' }}>
            <input style={S.input} placeholder="Type to search contacts..."
              value={contactSearch || subjectName}
              onChange={e => {
                setContactSearch(e.target.value);
                setSubjectName(e.target.value);
                setSubjectEntityId(null);
              }} />
            {contactSearch && filteredContacts.length > 0 && !subjectEntityId && (
              <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10,
                background: C.cardBg || '#1a1f2e', border: `1px solid ${C.border}`,
                borderRadius: 4, maxHeight: 150, overflowY: 'auto' }}>
                {filteredContacts.map(c => (
                  <div key={c.id} onClick={() => {
                    setSubjectName(c.display_name);
                    setSubjectEntityId(c.id);
                    setContactSearch('');
                  }} style={{ padding: '4px 8px', cursor: 'pointer', fontSize: 12, color: C.text,
                    borderBottom: `1px solid ${C.border}` }}
                    onMouseEnter={e => e.target.style.background = C.accent + '20'}
                    onMouseLeave={e => e.target.style.background = 'transparent'}>
                    {c.display_name}
                  </div>
                ))}
              </div>
            )}
          </div>
          {subjectEntityId && <span style={{ fontSize: 10, color: C.success }}>✓ Linked</span>}
        </div>
      </div>
      <div style={{ marginBottom: 8 }}>
        <label style={S.label}>Claim Text *</label>
        <textarea style={{ ...S.textarea, height: 60 }} placeholder="What was said or implied..."
          value={claimText} onChange={e => setClaimText(e.target.value)} />
      </div>
      {claimType === 'commitment' && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={S.label}>Firmness</label>
            <select style={S.select} value={firmness} onChange={e => setFirmness(e.target.value)}>
              <option value="">unclassified</option>
              <option value="required">required</option>
              <option value="concrete">concrete</option>
              <option value="intentional">intentional</option>
              <option value="tentative">tentative</option>
              <option value="social">social</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label style={S.label}>Direction</label>
            <select style={S.select} value={direction} onChange={e => setDirection(e.target.value)}>
              <option value="">unknown</option>
              <option value="owed_by_me">owed_by_me</option>
              <option value="owed_to_me">owed_to_me</option>
              <option value="owed_by_other">owed_by_other</option>
              <option value="mutual">mutual</option>
            </select>
          </div>
        </div>
      )}
      <div style={{ marginBottom: 8 }}>
        <label style={S.label}>Evidence Quote (optional)</label>
        <input style={S.input} placeholder="Verbatim quote from transcript..."
          value={evidenceQuote} onChange={e => setEvidenceQuote(e.target.value)} />
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button onClick={onCancel}
          style={{ fontSize: 11, padding: '4px 12px', borderRadius: 3,
            border: `1px solid ${C.border}`, background: 'transparent',
            color: C.textDim, cursor: 'pointer' }}>Cancel</button>
        <button onClick={handleSubmit} disabled={saving || !claimText.trim()}
          style={{ fontSize: 11, padding: '4px 12px', borderRadius: 3, border: 'none',
            background: C.accent, color: '#fff', cursor: 'pointer',
            opacity: (saving || !claimText.trim()) ? 0.5 : 1 }}>
          {saving ? 'Creating...' : 'Create Claim'}
        </button>
      </div>
    </div>
  );
}


