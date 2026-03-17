import { useState } from 'react';
import { api } from '../../api';
import { C } from "../../utils/colors";
import { cardStyle } from './styles';

export function BulkReassignModal({
  conversationId, linkedEntities, contacts, onClose, onComplete, onSwitchTab,
  searchContactsFn = api.searchContacts,
  bulkReassignFn = api.bulkReassign,
  initialPreview, initialResult,
}) {
  const [fromEntityId, setFromEntityId] = useState('');
  const [toEntityId, setToEntityId] = useState('');
  const [scope, setScope] = useState('all');
  const [toSearch, setToSearch] = useState('');
  const [toResults, setToResults] = useState([]);
  const [preview, setPreview] = useState(initialPreview || null);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(initialResult || null);
  const [error, setError] = useState(null);
  const [nameOverride, setNameOverride] = useState('');

  const handleSearchTo = async (q) => {
    setToSearch(q);
    if (q.length < 2) { setToResults([]); return; }
    try {
      const r = await searchContactsFn(q, 10);
      setToResults(r.filter(c => c.is_confirmed !== 0));
    } catch {
      setToResults(contacts.filter(c => c.is_confirmed !== 0 && c.canonical_name.toLowerCase().includes(q.toLowerCase())).slice(0, 10));
    }
  };

  const handlePreview = async () => {
    if (!fromEntityId || !toEntityId) return;
    setError(null);
    try {
      const p = await bulkReassignFn(conversationId, fromEntityId, toEntityId, scope, true);
      setPreview(p);
    } catch (e) {
      setError(e.message);
    }
  };

  const handleExecute = async () => {
    if (!fromEntityId || !toEntityId) return;
    setExecuting(true);
    setError(null);
    try {
      const r = await bulkReassignFn(conversationId, fromEntityId, toEntityId, scope, false);
      setResult(r);
    } catch (e) {
      setError(e.message);
    }
    setExecuting(false);
  };

  const selectedToName = contacts.find(c => c.id === toEntityId)?.canonical_name || '';

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ ...cardStyle, width: 520, maxHeight: '80vh', overflow: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: C.text }}>Bulk Reassign Speaker</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.textDim, fontSize: 18, cursor: 'pointer' }}>&times;</button>
        </div>

        {result ? (
          <div>
            <div style={{ padding: 16, borderRadius: 6, background: `${C.success}15`, border: `1px solid ${C.success}33`, marginBottom: 16 }}>
              <p style={{ fontSize: 14, fontWeight: 600, color: C.success, marginBottom: 8 }}>Reassignment Complete</p>
              <p style={{ fontSize: 13, color: C.text }}>
                {result.from_entity} &rarr; {result.to_entity}
              </p>
              <div style={{ fontSize: 12, color: C.textMuted, marginTop: 8 }}>
                <p>{result.claims_updated} claims updated</p>
                <p>{result.transcripts_updated} transcript segments updated</p>
                <p>{result.beliefs_invalidated} beliefs set to under_review</p>
                {result.ambiguous_claims_flagged > 0 && (
                  <p style={{ color: C.amber }}>{result.ambiguous_claims_flagged} claims flagged as ambiguous</p>
                )}
              </div>
              {result.transcript_review_recommended && (
                <p style={{ fontSize: 12, color: C.warning, marginTop: 8 }}>
                  Transcript speaker labels were also updated. Review the Transcript tab to verify.
                </p>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {result.transcript_review_recommended && (
                <button onClick={() => { onComplete(); if (onSwitchTab) onSwitchTab('transcript'); }}
                  style={{ flex: 1, padding: '10px 16px', background: `${C.warning}22`, color: C.warning,
                    border: `1px solid ${C.warning}44`, borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                  Review Transcript
                </button>
              )}
              <button onClick={onComplete} style={{ flex: 1, padding: '10px 16px', background: C.accent, color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                Close & Refresh
              </button>
            </div>
          </div>
        ) : (
          <div>
            {/* From entity selector */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: C.textMuted, display: 'block', marginBottom: 6 }}>Reassign all references from:</label>
              <select value={fromEntityId} onChange={e => { setFromEntityId(e.target.value); setPreview(null); }}
                style={{ width: '100%', padding: '8px 10px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 13 }}>
                <option value="">Select entity...</option>
                {Object.entries(linkedEntities).map(([eId, eName]) => (
                  <option key={eId} value={eId}>{eName}</option>
                ))}
              </select>
            </div>

            {/* To entity selector */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: C.textMuted, display: 'block', marginBottom: 6 }}>Reassign to:</label>
              {toEntityId ? (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 13, color: C.text, padding: '8px 10px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, flex: 1 }}>
                    {selectedToName}
                  </span>
                  <button onClick={() => { setToEntityId(''); setToSearch(''); setPreview(null); }}
                    style={{ fontSize: 12, color: C.textDim, background: 'none', border: `1px solid ${C.border}`, borderRadius: 4, padding: '6px 10px', cursor: 'pointer' }}>
                    Change
                  </button>
                </div>
              ) : (
                <div>
                  <input value={toSearch} onChange={e => handleSearchTo(e.target.value)}
                    placeholder="Search contacts..."
                    style={{ width: '100%', padding: '8px 10px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 13, outline: 'none' }} />
                  {toResults.length > 0 && (
                    <div style={{ border: `1px solid ${C.border}`, borderRadius: 4, marginTop: 4, maxHeight: 160, overflow: 'auto', background: C.bg }}>
                      {toResults.map(c => (
                        <button key={c.id} onClick={() => { setToEntityId(c.id); setToResults([]); setToSearch(''); setPreview(null); }}
                          style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 10px', fontSize: 12, color: C.text, background: 'transparent', border: 'none', cursor: 'pointer' }}
                          onMouseEnter={e => e.target.style.background = C.cardHover}
                          onMouseLeave={e => e.target.style.background = 'transparent'}>
                          {c.canonical_name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Scope selector */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: C.textMuted, display: 'block', marginBottom: 6 }}>Scope:</label>
              <div style={{ display: 'flex', gap: 8 }}>
                {['all', 'claims_only', 'transcript_only'].map(s => (
                  <button key={s} onClick={() => { setScope(s); setPreview(null); }}
                    style={{ padding: '6px 12px', borderRadius: 4, fontSize: 12, cursor: 'pointer', border: 'none',
                      background: scope === s ? C.accent : `${C.accent}15`, color: scope === s ? '#fff' : C.textMuted }}>
                    {s === 'all' ? 'All' : s === 'claims_only' ? 'Claims only' : 'Transcript only'}
                  </button>
                ))}
              </div>
            </div>

            {/* Name override */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: C.textMuted, display: 'block', marginBottom: 6 }}>
                Display Name Override <span style={{ color: C.textDim, fontWeight: 400 }}>(optional)</span>
              </label>
              <input value={nameOverride} onChange={e => setNameOverride(e.target.value)}
                placeholder="Leave empty to use contact's canonical name"
                style={{ width: '100%', padding: '8px 10px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 13, outline: 'none' }} />
              <p style={{ fontSize: 11, color: C.textDim, marginTop: 4 }}>
                Override the name used in claim text replacement (e.g., correct a misspelling)
              </p>
            </div>

            {error && (
              <div style={{ padding: 10, borderRadius: 4, background: `${C.danger}15`, border: `1px solid ${C.danger}33`, color: C.danger, fontSize: 12, marginBottom: 16 }}>
                {error}
              </div>
            )}

            {/* Preview button */}
            {!preview && (
              <button onClick={handlePreview} disabled={!fromEntityId || !toEntityId}
                style={{ width: '100%', padding: '10px 16px', background: `${C.accent}22`, color: C.accent,
                  border: `1px solid ${C.accent}44`, borderRadius: 6, fontSize: 13, cursor: 'pointer',
                  opacity: (!fromEntityId || !toEntityId) ? 0.5 : 1 }}>
                Preview Changes
              </button>
            )}

            {/* Preview results */}
            {preview && (
              <div style={{ marginTop: 8 }}>
                <div style={{ padding: 12, borderRadius: 6, background: `${C.warning}10`, border: `1px solid ${C.warning}33`, marginBottom: 12 }}>
                  <p style={{ fontSize: 13, fontWeight: 600, color: C.warning, marginBottom: 4 }}>Preview: {preview.from_entity} &rarr; {preview.to_entity}</p>
                  <div style={{ fontSize: 12, color: C.textMuted }}>
                    <p>{preview.claims_affected} claims will be reassigned</p>
                    <p>{preview.transcript_segments_affected} transcript segments will be updated</p>
                    <p>{preview.belief_evidence_links_affected} belief evidence links affected</p>
                  </div>
                </div>

                {preview.sample_claims?.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <p style={{ fontSize: 11, color: C.textDim, marginBottom: 6, textTransform: 'uppercase', fontWeight: 600 }}>Sample changes:</p>
                    {preview.sample_claims.map((sc, i) => (
                      <div key={i} style={{ fontSize: 12, padding: '6px 0', borderBottom: `1px solid ${C.border}` }}>
                        <span style={{ color: C.danger, textDecoration: 'line-through' }}>{sc.old_subject}</span>
                        {' \u2192 '}
                        <span style={{ color: C.success }}>{sc.new_subject}</span>
                        <p style={{ color: C.textDim, marginTop: 2, fontSize: 11 }}>{sc.claim_text?.slice(0, 120)}</p>
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ display: 'flex', gap: 8 }}>
                  <button onClick={() => setPreview(null)}
                    style={{ flex: 1, padding: '10px 16px', background: 'transparent', color: C.textMuted,
                      border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                    Cancel
                  </button>
                  <button onClick={handleExecute} disabled={executing}
                    style={{ flex: 1, padding: '10px 16px', background: C.danger, color: '#fff',
                      border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer',
                      opacity: executing ? 0.7 : 1 }}>
                    {executing ? 'Executing...' : `Reassign ${preview.claims_affected} Claims`}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// EPISODES TAB — Primary Review Surface
