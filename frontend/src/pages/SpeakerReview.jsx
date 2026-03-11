import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { api } from '../api';

const C = {
  bg: '#0a0f1a', card: '#111827', cardHover: '#1a2234',
  border: '#1f2937', text: '#e5e7eb',
  textMuted: '#9ca3af', textDim: '#6b7280',
  accent: '#3b82f6', success: '#10b981', warning: '#f59e0b',
  danger: '#ef4444', purple: '#a78bfa', amber: '#f59e0b',
};

const speakerColors = ['#60a5fa', '#f472b6', '#34d399', '#fbbf24', '#a78bfa', '#fb923c'];

function SpeakerCard({ label, match, color, transcripts, onPlay, onAssign, onCreateAndAssign, onMerge, allLabels, contacts, searchQuery, onSearchChange }) {
  const [showAssign, setShowAssign] = useState(false);
  const [showMerge, setShowMerge] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createForm, setCreateForm] = useState({ name: '', organization: '', email: '', phone: '', aliases: '', pushToCRM: true });
  const [creating, setCreating] = useState(false);

  const segCount = transcripts.filter(t => t.speaker_label === label).length;
  const totalDur = transcripts
    .filter(t => t.speaker_label === label)
    .reduce((sum, t) => sum + (parseFloat(t.end_time || 0) - parseFloat(t.start_time || 0)), 0);

  const matchMethod = match?.match_method || 'unmatched';
  const confidence = match?.similarity_score || 0;
  const resolvedName = match?.contact_name || match?.profile_name || null;

  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
      padding: 16, minWidth: 220, flex: '1 1 220px',
      borderTop: `3px solid ${color}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.text }}>
            {resolvedName || label}
          </div>
          {resolvedName && (
            <div style={{ fontSize: 11, color: C.textDim }}>{label}</div>
          )}
        </div>
        <span style={{
          fontSize: 10, padding: '2px 6px', borderRadius: 4,
          background: matchMethod === 'unmatched' ? `${C.danger}22` : `${C.success}22`,
          color: matchMethod === 'unmatched' ? C.danger : C.success,
          fontWeight: 500,
        }}>
          {matchMethod}{confidence > 0 ? ` ${Math.round(confidence * 100)}%` : ''}
        </span>
      </div>

      <div style={{ fontSize: 12, color: C.textDim, marginBottom: 12 }}>
        {segCount} segments &middot; {Math.round(totalDur)}s total
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button onClick={() => onPlay(label)}
          style={{ padding: '4px 10px', fontSize: 11, background: `${color}22`, color, border: `1px solid ${color}44`, borderRadius: 4, cursor: 'pointer' }}>
          &#9654; Sample
        </button>
        <button onClick={() => { setShowAssign(!showAssign); setShowMerge(false); }}
          style={{ padding: '4px 10px', fontSize: 11, background: `${C.accent}22`, color: C.accent, border: `1px solid ${C.accent}44`, borderRadius: 4, cursor: 'pointer' }}>
          Assign
        </button>
        {allLabels.length > 1 && (
          <button onClick={() => { setShowMerge(!showMerge); setShowAssign(false); }}
            style={{ padding: '4px 10px', fontSize: 11, background: `${C.amber}22`, color: C.amber, border: `1px solid ${C.amber}44`, borderRadius: 4, cursor: 'pointer' }}>
            Merge
          </button>
        )}
      </div>

      {showAssign && (
        <div style={{ marginTop: 8 }}>
          <input
            type="text"
            placeholder="Search contacts..."
            value={searchQuery}
            onChange={e => onSearchChange(e.target.value)}
            style={{
              width: '100%', padding: '6px 8px', fontSize: 12,
              background: C.bg, color: C.text, border: `1px solid ${C.border}`,
              borderRadius: 4, outline: 'none', boxSizing: 'border-box',
            }}
          />
          {contacts.length > 0 && (
            <div style={{ maxHeight: 150, overflowY: 'auto', marginTop: 4, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4 }}>
              {contacts.map(c => (
                <div key={c.id}
                  onClick={() => { onAssign(label, c.id); setShowAssign(false); }}
                  style={{
                    padding: '6px 8px', fontSize: 12, color: C.text, cursor: 'pointer',
                    borderBottom: `1px solid ${C.border}`,
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  {c.canonical_name || c.name}
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${C.border}` }}>
            <button
              onClick={() => { setShowCreateForm(true); setShowAssign(false); setCreateForm({ name: '', organization: '', email: '', phone: '', aliases: '', pushToCRM: true }); }}
              style={{
                width: '100%', padding: '6px 8px', fontSize: 12,
                background: C.success + '15', color: C.success,
                border: '1px dashed ' + C.success + '44',
                borderRadius: 4, cursor: 'pointer', textAlign: 'left',
              }}
            >
              + Create New Contact
            </button>
          </div>
        </div>
      )}

      {showMerge && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, color: C.textDim, marginBottom: 4 }}>Merge into:</div>
          {allLabels.filter(l => l !== label).map(l => (
            <div key={l}
              onClick={() => { onMerge(label, l); setShowMerge(false); }}
              style={{
                padding: '4px 8px', fontSize: 12, color: C.text, cursor: 'pointer',
                borderRadius: 4,
              }}
              onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              {l}
            </div>
          ))}
        </div>
      )}

      {showCreateForm && (() => {
        const inputStyle = {
          width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4,
          background: C.bg, color: C.text, border: `1px solid ${C.border}`,
          outline: 'none', boxSizing: 'border-box',
        };
        return (
          <div style={{ marginTop: 8, padding: 10, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 6 }}>
            <div style={{ fontSize: 11, color: C.textMuted, marginBottom: 8, fontWeight: 600 }}>
              Create New Contact
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 6 }}>
              <div>
                <label style={{ fontSize: 10, color: C.textDim, display: 'block', marginBottom: 2 }}>Full Name *</label>
                <input value={createForm.name}
                  onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))}
                  style={inputStyle} placeholder="First Last" />
              </div>
              <div>
                <label style={{ fontSize: 10, color: C.textDim, display: 'block', marginBottom: 2 }}>Organization</label>
                <input value={createForm.organization}
                  onChange={e => setCreateForm(f => ({ ...f, organization: e.target.value }))}
                  style={inputStyle} placeholder="Company" />
              </div>
              <div>
                <label style={{ fontSize: 10, color: C.textDim, display: 'block', marginBottom: 2 }}>Email</label>
                <input value={createForm.email}
                  onChange={e => setCreateForm(f => ({ ...f, email: e.target.value }))}
                  style={inputStyle} placeholder="email@example.com" type="email" />
              </div>
              <div>
                <label style={{ fontSize: 10, color: C.textDim, display: 'block', marginBottom: 2 }}>Phone</label>
                <input value={createForm.phone}
                  onChange={e => setCreateForm(f => ({ ...f, phone: e.target.value }))}
                  style={inputStyle} placeholder="(555) 123-4567" type="tel" />
              </div>
            </div>
            <div style={{ marginBottom: 6 }}>
              <label style={{ fontSize: 10, color: C.textDim, display: 'block', marginBottom: 2 }}>Aliases (semicolon-separated)</label>
              <input value={createForm.aliases}
                onChange={e => setCreateForm(f => ({ ...f, aliases: e.target.value }))}
                style={inputStyle} placeholder="Nick; Nickname" />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <input type="checkbox" checked={createForm.pushToCRM}
                onChange={e => setCreateForm(f => ({ ...f, pushToCRM: e.target.checked }))}
                id={`push-crm-${label}`} />
              <label htmlFor={`push-crm-${label}`}
                style={{ fontSize: 11, color: C.textMuted, cursor: 'pointer' }}>
                Push to Networking App
              </label>
            </div>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowCreateForm(false)}
                style={{
                  padding: '5px 12px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                  background: C.card, color: C.textDim, border: `1px solid ${C.border}`,
                }}>
                Cancel
              </button>
              <button
                onClick={async () => {
                  setCreating(true);
                  try {
                    await onCreateAndAssign(label, createForm);
                    setShowCreateForm(false);
                    setCreateForm({ name: '', organization: '', email: '', phone: '', aliases: '', pushToCRM: true });
                  } catch (e) {
                    alert('Failed to create contact: ' + e.message);
                  }
                  setCreating(false);
                }}
                disabled={!createForm.name.trim() || creating}
                style={{
                  padding: '5px 12px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                  background: C.success + '22', color: C.success,
                  border: `1px solid ${C.success}44`,
                  opacity: createForm.name.trim() && !creating ? 1 : 0.4,
                }}>
                {creating ? 'Creating...' : 'Create & Assign'}
              </button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

export default function SpeakerReview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [convo, setConvo] = useState(null);
  const [transcripts, setTranscripts] = useState([]);
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filteredContacts, setFilteredContacts] = useState([]);
  const [playingLabel, setPlayingLabel] = useState(null);
  const audioRef = useRef(null);

  const loadData = useCallback(async () => {
    try {
      const [convoData, matchData] = await Promise.all([
        api.conversation(id),
        api.speakerMatches(id),
      ]);
      setConvo(convoData?.conversation || convoData);
      setMatches(matchData || []);

      // Extract transcript segments from conversation detail
      const segs = convoData?.transcript || [];
      setTranscripts(segs);
    } catch (e) {
      console.error('Failed to load speaker review data:', e);
    }
    setLoading(false);
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  // Search contacts
  useEffect(() => {
    if (searchQuery.length < 2) { setFilteredContacts([]); return; }
    const timer = setTimeout(() => {
      api.searchContacts(searchQuery, 10)
        .then(data => { const all = data?.contacts || data || []; setFilteredContacts(all.filter(c => c.is_confirmed !== 0)); })
        .catch(() => setFilteredContacts([]));
    }, 200);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Get unique speaker labels
  const speakerLabels = [...new Set(transcripts.map(t => t.speaker_label).filter(Boolean))].sort();

  // Build match map: label -> best match
  const matchMap = {};
  for (const m of matches) {
    if (!matchMap[m.speaker_label] || (m.similarity_score > (matchMap[m.speaker_label].similarity_score || 0))) {
      matchMap[m.speaker_label] = m;
    }
  }

  const handlePlay = (label) => {
    if (audioRef.current) {
      audioRef.current.pause();
    }
    const url = api.speakerSampleUrl(id, label);
    const audio = new Audio(url);
    audioRef.current = audio;
    setPlayingLabel(label);
    audio.play().catch(() => {});
    audio.onended = () => setPlayingLabel(null);
  };

  const handlePlaySegment = (startTime, endTime) => {
    if (audioRef.current) audioRef.current.pause();
    const url = api.audioClipUrl(id, startTime, endTime);
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.play().catch(() => {});
  };

  const handleAssign = async (label, contactId) => {
    try {
      await api.correctSpeaker(id, label, contactId);
      setSearchQuery('');
      setFilteredContacts([]);
      loadData();
    } catch (e) {
      console.error('Failed to assign speaker:', e);
    }
  };

  const handleCreateAndAssign = async (label, formData) => {
    const result = await api.createContact({
      canonical_name: formData.name.trim(),
      organization: formData.organization || undefined,
      email: formData.email || undefined,
      phone: formData.phone || undefined,
      aliases: formData.aliases || undefined,
      push_to_networking_app: formData.pushToCRM,
      source_conversation_id: id,
    });
    await api.correctSpeaker(id, label, result.contact_id);
    setSearchQuery('');
    setFilteredContacts([]);
    loadData();
  };

  const handleMerge = async (fromLabel, toLabel) => {
    try {
      await api.mergeSpeakers(id, fromLabel, toLabel);
      loadData();
    } catch (e) {
      console.error('Failed to merge speakers:', e);
    }
  };

  const handleConfirmAndExtract = async () => {
    setConfirming(true);
    try {
      await api.confirmSpeakers(id);
      navigate('/review');
    } catch (e) {
      console.error('Failed to confirm speakers:', e);
      setConfirming(false);
    }
  };

  const [discarding, setDiscarding] = useState(false);
  const handleDiscard = async () => {
    if (!window.confirm('Discard this conversation? It will be removed from all review queues.')) return;
    setDiscarding(true);
    try {
      await api.discardConversation(id, 'discarded_from_speaker_review');
      navigate('/review');
    } catch (e) {
      console.error('Failed to discard:', e);
      setDiscarding(false);
    }
  };

  if (loading) {
    return <div style={{ padding: 48, textAlign: 'center', color: C.textDim }}>Loading speaker data...</div>;
  }

  if (!convo) {
    return <div style={{ padding: 48, textAlign: 'center', color: C.danger }}>Conversation not found</div>;
  }

  return (
    <div style={{ padding: '24px 0' }}>
      <Link to="/review" style={{ color: C.accent, fontSize: 13, textDecoration: 'none' }}>&larr; Back to Review</Link>

      <div style={{ marginTop: 16, marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: C.text, margin: 0 }}>Speaker Review</h1>
          <p style={{ fontSize: 13, color: C.textDim, marginTop: 4 }}>
            {convo.source} capture &middot;
            {convo.duration_seconds ? ` ${Math.round(convo.duration_seconds / 60)}min` : ''} &middot;
            {speakerLabels.length} speakers &middot;
            {transcripts.length} segments
          </p>
        </div>
        {convo.processing_status === 'awaiting_speaker_review' && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleDiscard}
              disabled={discarding}
              style={{
                padding: '10px 16px', background: 'transparent', color: C.danger,
                border: '1px solid ' + C.danger + '44', borderRadius: 6, fontSize: 13,
                cursor: 'pointer', opacity: discarding ? 0.7 : 1,
              }}
            >
              {discarding ? 'Discarding...' : '✗ Discard'}
            </button>
            <button
              onClick={handleConfirmAndExtract}
              disabled={confirming}
              style={{
                padding: '10px 20px', background: C.success, color: '#fff', border: 'none',
                borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: 'pointer',
                opacity: confirming ? 0.7 : 1,
              }}
            >
              {confirming ? 'Starting Extraction...' : '✓ Confirm & Start Extraction'}
            </button>
          </div>
        )}
      </div>

      {/* Speaker Summary Cards */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
        {speakerLabels.map((label, i) => (
          <SpeakerCard
            key={label}
            label={label}
            match={matchMap[label]}
            color={speakerColors[i % speakerColors.length]}
            transcripts={transcripts}
            onPlay={handlePlay}
            onAssign={handleAssign}
            onCreateAndAssign={handleCreateAndAssign}
            onMerge={handleMerge}
            allLabels={speakerLabels}
            contacts={filteredContacts}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
          />
        ))}
      </div>

      {/* Transcript View */}
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20 }}>
        <h3 style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 16, marginTop: 0 }}>
          Transcript
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {transcripts.map((seg, i) => {
            const labelIdx = speakerLabels.indexOf(seg.speaker_label);
            const color = speakerColors[labelIdx % speakerColors.length] || C.textDim;
            const match = matchMap[seg.speaker_label];
            const name = match?.contact_name || match?.profile_name || seg.speaker_label;
            const startTime = parseFloat(seg.start_time || 0);
            const endTime = parseFloat(seg.end_time || 0);

            return (
              <div key={seg.id || i} style={{ display: 'flex', gap: 8, padding: '4px 0', fontSize: 13 }}>
                <button
                  onClick={() => handlePlaySegment(startTime, endTime)}
                  title="Play segment"
                  style={{
                    background: 'transparent', border: 'none', color: C.textDim,
                    cursor: 'pointer', fontSize: 10, padding: '2px 4px', flexShrink: 0,
                  }}
                >&#9654;</button>
                <span style={{ color: C.textDim, fontSize: 11, width: 70, flexShrink: 0, paddingTop: 2 }}>
                  {Math.floor(startTime / 60)}:{String(Math.floor(startTime % 60)).padStart(2, '0')}
                </span>
                <span style={{
                  color, fontWeight: 500, width: 120, flexShrink: 0, paddingTop: 1,
                  fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {name}
                </span>
                <span style={{ color: C.text, lineHeight: 1.5 }}>
                  {seg.text}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
