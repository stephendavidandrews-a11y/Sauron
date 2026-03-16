import { useState, useEffect, useCallback } from 'react';
import { api } from '../../../api';
import { C, cardStyle } from '../styles';

export function TranscriptTab({ transcript, conversationId, contacts }) {
  const [editingSeg, setEditingSeg] = useState(null);
  const [editText, setEditText] = useState('');
  const [correctedSegs, setCorrectedSegs] = useState(new Set());
  const [speakerDropdown, setSpeakerDropdown] = useState(null);
  const [speakerSearch, setSpeakerSearch] = useState('');
  const [localTranscript, setLocalTranscript] = useState(transcript);

  useEffect(() => setLocalTranscript(transcript), [transcript]);

  const handleSaveText = async (seg) => {
    try {
      await api.editTranscript(seg.id, editText);
      setCorrectedSegs(prev => new Set(prev).add(seg.id));
      setLocalTranscript(prev => prev.map(s => s.id === seg.id ? { ...s, text: editText, user_corrected: 1 } : s));
      setEditingSeg(null);
    } catch (e) { console.error('Edit failed', e); }
  };

  const handleSpeakerChange = async (seg, contactId) => {
    try {
      await api.correctSpeaker(conversationId, seg.speaker_label, contactId);
      const contact = contacts.find(c => c.id === contactId);
      setLocalTranscript(prev => prev.map(s =>
        s.speaker_label === seg.speaker_label ? { ...s, speaker_id: contactId, speaker_name: contact?.canonical_name || contactId } : s
      ));
      setSpeakerDropdown(null);
    } catch (e) { console.error('Speaker correction failed', e); }
  };

  const filteredContacts = speakerSearch
    ? contacts.filter(c => c.canonical_name.toLowerCase().includes(speakerSearch.toLowerCase())).slice(0, 10)
    : contacts.slice(0, 10);

  return (
    <div style={cardStyle}>
      {localTranscript.length === 0 ? (
        <p style={{ color: C.textDim, fontSize: 13, textAlign: 'center', padding: 30 }}>No transcript available.</p>
      ) : (
        <div>
          {localTranscript.map((seg, i) => (
            <div key={seg.id || i} style={{
              padding: '8px 0', borderBottom: i < localTranscript.length - 1 ? `1px solid ${C.border}` : 'none',
              display: 'flex', gap: 8, alignItems: 'flex-start',
            }}>
              <div style={{ position: 'relative', flexShrink: 0, minWidth: 100 }}>
                <button onClick={() => { setSpeakerDropdown(speakerDropdown === seg.id ? null : seg.id); setSpeakerSearch(''); }}
                  style={{ fontSize: 12, fontWeight: 600, background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px', borderRadius: 3,
                    color: seg.speaker_label === 'SPEAKER_00' ? C.accent : C.purple }}>
                  {seg.speaker_name || seg.speaker_label || 'Unknown'}
                </button>
                {seg.speaker_id && (
                  <span style={{ fontSize: 9, color: seg.voice_sample_count ? C.success : C.textDim, marginLeft: 2 }}
                    title={seg.voice_sample_count ? `Voice enrolled (${seg.voice_sample_count} samples)` : 'Identified (no voiceprint)'}>
                    {seg.voice_sample_count ? '🎤' : ''}
                  </span>
                )}
                {!seg.speaker_id && (
                  <span style={{ fontSize: 9, color: C.warning, marginLeft: 2 }} title="Unknown speaker — assign to enroll">?</span>
                )}
                {speakerDropdown === seg.id && (
                  <div style={{ position: 'absolute', left: 0, top: '100%', marginTop: 4, zIndex: 50,
                    background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, padding: 8,
                    minWidth: 220, boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
                    <input value={speakerSearch} onChange={e => setSpeakerSearch(e.target.value)}
                      placeholder="Search..." autoFocus
                      style={{ width: '100%', padding: '4px 6px', fontSize: 12, background: C.bg,
                        border: `1px solid ${C.border}`, borderRadius: 3, color: C.text, marginBottom: 4, outline: 'none' }} />
                    {filteredContacts.map(c => (
                      <button key={c.id} onClick={() => handleSpeakerChange(seg, c.id)}
                        style={{ display: 'block', width: '100%', textAlign: 'left', padding: '5px 6px',
                          fontSize: 12, color: C.text, background: 'transparent', border: 'none', cursor: 'pointer', borderRadius: 3 }}
                        onMouseEnter={e => e.target.style.background = C.cardHover}
                        onMouseLeave={e => e.target.style.background = 'transparent'}>
                        {c.canonical_name}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <span style={{ fontSize: 11, color: C.textDim, flexShrink: 0, minWidth: 40 }}>
                {seg.start_time ? `${Number(seg.start_time).toFixed(1)}s` : ''}
              </span>

              <div style={{ flex: 1 }}>
                {editingSeg === seg.id ? (
                  <div>
                    <textarea value={editText} onChange={e => setEditText(e.target.value)}
                      style={{ width: '100%', minHeight: 40, background: C.bg, border: `1px solid ${C.accent}`,
                        borderRadius: 4, padding: 6, fontSize: 13, color: C.text, resize: 'vertical', fontFamily: 'inherit' }} />
                    <div style={{ display: 'flex', gap: 4, marginTop: 4, justifyContent: 'flex-end' }}>
                      <button onClick={() => setEditingSeg(null)}
                        style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3, border: `1px solid ${C.border}`,
                          background: 'transparent', color: C.textDim, cursor: 'pointer' }}>Cancel</button>
                      <button onClick={() => handleSaveText(seg)}
                        style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3, border: 'none',
                          background: C.accent, color: '#fff', cursor: 'pointer' }}>Save</button>
                    </div>
                  </div>
                ) : (
                  <span onClick={() => { setEditingSeg(seg.id); setEditText(seg.text); }}
                    style={{ fontSize: 13, color: C.text, cursor: 'pointer', display: 'inline' }}
                    title="Click to edit">
                    {seg.text}
                    {(seg.user_corrected || correctedSegs.has(seg.id)) && (
                      <span style={{ fontSize: 10, color: C.warning, marginLeft: 4 }} title="User corrected">{'\u270E'}</span>
                    )}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// CLAIMS TAB — Flat list
// ═══════════════════════════════════════════════════════
