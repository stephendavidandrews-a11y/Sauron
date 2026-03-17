import { useState, useEffect, useCallback } from 'react';
import { api } from '../../../api';
import { C } from "../../../utils/colors";
import { cardStyle } from '../styles';

export function RelationalReferencesBanner({
  conversationId, contacts, onResolved,
  initialClaims,
  loadRelationalClaimsFn = api.unresolvedRelational,
  searchContactsFn = api.searchContacts,
  linkEntityFn = api.linkEntity,
  saveRelationshipFn = api.saveRelationship,
}) {
  const [claims, setClaims] = useState(initialClaims || []);
  const [loading, setLoading] = useState(!initialClaims);
  const [linkingId, setLinkingId] = useState(null);
  const [linkSearch, setLinkSearch] = useState('');
  const [linkResults, setLinkResults] = useState([]);
  const [linkedPeople, setLinkedPeople] = useState({});  // claimId -> [{name, id}]
  const [relPrompt, setRelPrompt] = useState(null);
  const [editingAnchorId, setEditingAnchorId] = useState(null);
  const [anchorSearch, setAnchorSearch] = useState('');
  const [anchorResults, setAnchorResults] = useState([]);

  useEffect(() => {
    if (initialClaims) return;
    loadRelationalClaimsFn(conversationId, 30)
      .then(d => setClaims(d.relational_claims || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conversationId, initialClaims, loadRelationalClaimsFn]);

  const handleSearch = async (q) => {
    setLinkSearch(q);
    if (q.length < 2) { setLinkResults([]); return; }
    try {
      const results = await searchContactsFn(q, 10);
      setLinkResults(results.filter(c => c.is_confirmed !== 0));
    } catch { setLinkResults([]); }
  };

  const handleLink = async (claim, contactId) => {
    try {
      const contact = contacts.find(c => c.id === contactId) || linkResults.find(c => c.id === contactId);
      const contactName = contact ? contact.canonical_name : '';
      const result = await linkEntityFn(conversationId, claim.id, contactId, claim.subject_name, null);

      // Track linked people for this claim
      setLinkedPeople(prev => ({
        ...prev,
        [claim.id]: [...(prev[claim.id] || []), { id: contactId, name: contactName }],
      }));

      // If relational reference detected, prompt to save relationship
      if (result && result.relational_ref) {
        const ref = result.relational_ref;
        const anchorContact = contacts.find(c => c.canonical_name === ref.anchor_name);
        if (anchorContact) {
          setRelPrompt({
            claimId: claim.id,
            anchorId: anchorContact.id,
            anchorName: ref.anchor_name,
            relationship: ref.relationship,
            isPlural: ref.is_plural,
            targetId: contactId,
            targetName: contactName,
            phrase: ref.phrase,
          });
        }
      }

      // Reset search but keep linking open for plurals
      setLinkSearch('');
      setLinkResults([]);
      if (!claim.is_plural) {
        setLinkingId(null);
      }
    } catch (e) { console.error('Link failed', e); }
  };

  const handleSaveRel = async () => {
    if (!relPrompt) return;
    try {
      const targets = relPrompt.targets || [{ id: relPrompt.targetId, name: relPrompt.targetName }];
      // Save one relationship per target (multi-target support, Bug 10)
      for (const target of targets) {
        await saveRelationshipFn(
          relPrompt.anchorId, relPrompt.relationship.trim(),
          target.id, target.name
        );
      }
      setRelPrompt(null);
      if (onResolved) onResolved();
    } catch (e) { console.error('Save relationship failed', e); }
  };

  const unresolved = claims.filter(c => !c.subject_entity_id || c.is_plural);
  if (loading || unresolved.length === 0) return null;

  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: '#ec4899' + '66',
      background: '#ec4899' + '0a',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 16 }}>🔗</span>
        <span style={{ color: '#ec4899', fontWeight: 600, fontSize: 14 }}>
          Relational References ({unresolved.length})
        </span>
        <span style={{ color: C.textDim, fontSize: 12 }}>
          — People mentioned by relationship that need linking to contacts
        </span>
      </div>

      {/* Relationship detail form (Bug 10) */}
      {relPrompt && (
        <div style={{
          padding: '14px 16px', marginBottom: 10, borderRadius: 6,
          background: C.success + '08', border: '1px solid ' + C.success + '33',
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.success, marginBottom: 10 }}>
            Save Relationship
          </div>

          {/* Relationship type — editable */}
          <div style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Relationship Type</label>
            <input
              value={relPrompt.relationship}
              onChange={e => setRelPrompt(p => ({ ...p, relationship: e.target.value }))}
              style={{ width: '100%', padding: '5px 8px', fontSize: 13, borderRadius: 4,
                background: C.bg, color: C.text, border: '1px solid ' + C.border, outline: 'none', boxSizing: 'border-box' }}
              placeholder="e.g., son, birth mother, colleague" />
          </div>

          {/* Source person (anchor) */}
          <div style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Source Person (who has this relationship)</label>
            <div style={{ fontSize: 13, color: '#ec4899', fontWeight: 500, padding: '5px 8px',
              background: C.card, borderRadius: 4, border: '1px solid ' + C.border }}>
              {relPrompt.anchorName}
            </div>
          </div>

          {/* Target person(s) — with "add another" */}
          <div style={{ marginBottom: 10 }}>
            <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 3 }}>Related To (target person)</label>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
              {(relPrompt.targets || [{ id: relPrompt.targetId, name: relPrompt.targetName }]).map((t, i) => (
                <span key={i} style={{
                  fontSize: 12, padding: '3px 8px', borderRadius: 4,
                  background: '#ec4899' + '22', color: '#ec4899', display: 'inline-flex', alignItems: 'center', gap: 4,
                }}>
                  {t.name}
                  {(relPrompt.targets || []).length > 1 && (
                    <button onClick={() => setRelPrompt(p => ({
                      ...p,
                      targets: (p.targets || []).filter((_, j) => j !== i),
                    }))} style={{ fontSize: 10, background: 'none', border: 'none', color: C.textDim, cursor: 'pointer', padding: 0 }}>&times;</button>
                  )}
                </span>
              ))}
            </div>
            {/* Add another target button + search */}
            {relPrompt.addingTarget ? (
              <div>
                <input
                  value={relPrompt.targetSearch || ''}
                  onChange={async (e) => {
                    const q = e.target.value;
                    setRelPrompt(p => ({ ...p, targetSearch: q }));
                    if (q.length >= 2) {
                      try {
                        const results = await searchContactsFn(q, 8);
                        setRelPrompt(p => ({ ...p, targetResults: results }));
                      } catch {}
                    }
                  }}
                  placeholder="Search contacts..."
                  autoFocus
                  style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4,
                    background: C.bg, color: C.text, border: '1px solid ' + C.border, outline: 'none', boxSizing: 'border-box' }}
                />
                {(relPrompt.targetResults || []).map(r => (
                  <div key={r.id}
                    onClick={() => {
                      const targets = relPrompt.targets || [{ id: relPrompt.targetId, name: relPrompt.targetName }];
                      if (!targets.find(t => t.id === r.id)) {
                        setRelPrompt(p => ({
                          ...p,
                          targets: [...targets, { id: r.id, name: r.canonical_name }],
                          addingTarget: false, targetSearch: '', targetResults: [],
                        }));
                      }
                    }}
                    style={{ padding: '5px 8px', fontSize: 12, color: C.text, cursor: 'pointer', borderRadius: 3 }}
                    onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                    {r.canonical_name}
                  </div>
                ))}
                <button onClick={() => setRelPrompt(p => ({ ...p, addingTarget: false }))}
                  style={{ fontSize: 11, color: C.textDim, background: 'none', border: 'none', cursor: 'pointer', marginTop: 4 }}>
                  Cancel
                </button>
              </div>
            ) : (
              <button onClick={() => setRelPrompt(p => ({ ...p, addingTarget: true }))}
                style={{ fontSize: 11, padding: '3px 8px', borderRadius: 4, cursor: 'pointer',
                  background: 'transparent', color: C.accent, border: '1px solid ' + C.accent + '44' }}>
                + Add another person
              </button>
            )}
          </div>

          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
            <button onClick={handleSaveRel} style={{
              padding: '6px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44', fontWeight: 500,
            }}>Save Relationship</button>
            <button onClick={() => setRelPrompt(null)} style={{
              padding: '6px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
              background: C.card, color: C.textDim, border: '1px solid ' + C.border,
            }}>Skip</button>
          </div>
        </div>
      )}

      {unresolved.map(c => {
        const linked = linkedPeople[c.id] || [];
        return (
          <div key={c.id} style={{
            padding: '10px 12px', marginBottom: 8,
            background: C.card, borderRadius: 6, border: '1px solid ' + C.border,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <span style={{ color: '#ec4899', fontSize: 12, fontWeight: 600 }}>
                  {c.anchor_reference && !['my','his','her','their'].includes(c.anchor_reference.toLowerCase())
                    ? c.anchor_reference + "'s " : ''}
                  {c.relational_term_raw || c.relational_term || 'relationship'}
                </span>
                {c.is_plural && (
                  <span style={{ color: C.warning, marginLeft: 6, fontSize: 11, fontWeight: 600 }}>
                    (multiple — link each person)
                  </span>
                )}
                {c.anchor_contact ? (
                  <span style={{ color: C.textDim, fontSize: 11, marginLeft: 8, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    anchor: {c.anchor_contact.canonical_name}
                    <button onClick={(e) => { e.stopPropagation(); setEditingAnchorId(editingAnchorId === c.id ? null : c.id); setAnchorSearch(''); setAnchorResults([]); }}
                      style={{ fontSize: 10, background: 'none', border: 'none', color: C.accent, cursor: 'pointer', padding: '0 2px' }}
                      title="Edit anchor">{editingAnchorId === c.id ? '\u2716' : '\u270E'}</button>
                  </span>
                ) : (
                  <button onClick={() => { setEditingAnchorId(editingAnchorId === c.id ? null : c.id); setAnchorSearch(''); setAnchorResults([]); }}
                    style={{ fontSize: 11, color: C.accent, background: 'none', border: 'none', cursor: 'pointer', marginLeft: 8 }}>
                    set anchor
                  </button>
                )}
                {/* Anchor edit search dropdown (Bug 5) */}
                {editingAnchorId === c.id && (
                  <div style={{ marginTop: 6, padding: 6, background: C.bg, borderRadius: 4 }}>
                    <input value={anchorSearch}
                      onChange={async (e) => {
                        setAnchorSearch(e.target.value);
                        if (e.target.value.length >= 2) {
                          try {
                            const r = await searchContactsFn(e.target.value, 8);
                            setAnchorResults(r);
                          } catch {}
                        } else { setAnchorResults([]); }
                      }}
                      placeholder="Search for anchor person..."
                      autoFocus
                      style={{ width: '100%', padding: '4px 8px', fontSize: 12, borderRadius: 3,
                        background: C.card, color: C.text, border: '1px solid ' + C.border, outline: 'none', boxSizing: 'border-box' }} />
                    {anchorResults.map(r => (
                      <div key={r.id}
                        onClick={() => {
                          // Update the claim's anchor_contact in local state
                          setClaims(prev => prev.map(cl =>
                            cl.id === c.id ? { ...cl, anchor_contact: { id: r.id, canonical_name: r.canonical_name }, anchor_reference: r.canonical_name } : cl
                          ));
                          setEditingAnchorId(null);
                          setAnchorSearch('');
                          setAnchorResults([]);
                        }}
                        style={{ padding: '4px 8px', fontSize: 12, color: C.text, cursor: 'pointer', borderRadius: 3 }}
                        onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                        {r.canonical_name}
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ fontSize: 12, color: C.textMuted, marginTop: 4 }}>
                  {c.claim_text?.slice(0, 140)}{c.claim_text?.length > 140 ? '...' : ''}
                </div>

                {/* Show already-linked people for this claim */}
                {linked.length > 0 && (
                  <div style={{ marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {linked.map((p, i) => (
                      <span key={i} style={{
                        fontSize: 11, padding: '2px 8px', borderRadius: 10,
                        background: C.success + '22', color: C.success,
                      }}>✓ {p.name}</span>
                    ))}
                  </div>
                )}
              </div>

              <button
                onClick={() => setLinkingId(linkingId === c.id ? null : c.id)}
                style={{
                  padding: '4px 10px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                  background: '#ec4899' + '22', color: '#ec4899',
                  border: '1px solid ' + '#ec4899' + '44', whiteSpace: 'nowrap',
                }}>
                {c.is_plural ? 'Link Person' : 'Link'}
              </button>
            </div>

            {/* Search dropdown */}
            {linkingId === c.id && (
              <div style={{ marginTop: 8, padding: 8, background: C.bg, borderRadius: 4 }}>
                <input
                  type="text" placeholder="Search contacts..."
                  value={linkSearch} onChange={e => handleSearch(e.target.value)}
                  autoFocus
                  style={{
                    width: '100%', padding: '6px 10px', fontSize: 13, borderRadius: 4,
                    background: C.card, color: C.text, border: '1px solid ' + C.border,
                    outline: 'none', boxSizing: 'border-box',
                  }}
                />
                {linkResults.length > 0 && (
                  <div style={{ marginTop: 4, maxHeight: 150, overflowY: 'auto' }}>
                    {linkResults.map(r => (
                      <div key={r.id}
                        onClick={() => handleLink(c, r.id)}
                        style={{
                          padding: '6px 10px', cursor: 'pointer', fontSize: 13,
                          color: C.text, borderRadius: 4,
                        }}
                        onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      >
                        {r.canonical_name}
                        {r.email && <span style={{ color: C.textDim, marginLeft: 8, fontSize: 11 }}>{r.email}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}


// ═══════════════════════════════════════════════════════
// OBJECTS REVIEW BANNER — non-person entities (orgs, legislation, topics)
// ═══════════════════════════════════════════════════════
