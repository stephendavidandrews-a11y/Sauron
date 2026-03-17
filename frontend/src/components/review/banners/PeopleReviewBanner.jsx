import { useState, useEffect, useCallback } from 'react';
import { api } from '../../../api';
import { C } from "../../../utils/colors";
import { cardStyle } from '../styles';

export function PeopleReviewBanner({
  conversationId, contacts, onResolved, onPeopleLoaded,
  initialPeople, pendingEntities: pendingEntitiesProp,
  textReplaceTarget, setTextReplaceTarget,
  loadPeopleFn = api.conversationPeople,
  confirmPersonFn = api.confirmPerson,
  skipPersonFn = api.skipPerson,
  unskipPersonFn = api.unskipPerson,
  dismissPersonFn = api.dismissPerson,
  searchContactsFn = api.searchContacts,
  linkProvisionalFn = api.linkProvisional,
  dismissProvisionalFn = api.dismissProvisional,
  confirmProvisionalFn = api.confirmProvisional,
  linkRemainingFn = api.linkRemainingClaims,
}) {
  const [people, setPeople] = useState(initialPeople || []);
  const [loading, setLoading] = useState(!initialPeople);
  const [expanded, setExpanded] = useState(false);
  const [linkingName, setLinkingName] = useState(null);
  const [linkSearch, setLinkSearch] = useState('');
  const [linkResults, setLinkResults] = useState([]);
  const [editingName, setEditingName] = useState(null);
  const [editForm, setEditForm] = useState({ name: '', organization: '', title: '', email: '', phone: '', aliases: '', notes: '' });
  const [actionLoading, setActionLoading] = useState(null);
  const [actionError, setActionError] = useState(null);

  const fetchPeople = useCallback(() => {
    if (initialPeople) return;
    loadPeopleFn(conversationId)
      .then(d => {
        const ppl = d.people || [];
        setPeople(ppl);
        // Report counts to parent
        const yellow = ppl.filter(p => p.status === 'auto_resolved').length;
        const red = ppl.filter(p => p.status === 'provisional' || p.status === 'unresolved').length;
        if (onPeopleLoaded) onPeopleLoaded({ yellow, red, total: ppl.length });
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conversationId, onPeopleLoaded]);

  useEffect(() => { fetchPeople(); }, [fetchPeople]);

  if (loading) return null;
  if (people.length === 0) return null;

  const nonSelf = people.filter(p => !p.is_self);
  const selfPeople = people.filter(p => p.is_self);
  const yellowPeople = nonSelf.filter(p => p.status === 'auto_resolved');
  const redPeople = nonSelf.filter(p => p.status === 'provisional' || p.status === 'unresolved');
  const greenPeople = nonSelf.filter(p => p.status === 'confirmed');
  const skippedPeople = nonSelf.filter(p => p.status === 'skipped');
  const allGreen = yellowPeople.length === 0 && redPeople.length === 0 && skippedPeople.length === 0;

  const handleConfirm = async (person) => {
    setActionLoading(person.original_name);
    try {
      await confirmPersonFn(conversationId, person.original_name, person.entity_id);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Confirm failed', e); }
    setActionLoading(null);
  };

  const handleSkip = async (person) => {
    setActionLoading(person.original_name);
    try {
      await skipPersonFn(conversationId, person.original_name, person.entity_id || null);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Skip failed', e); }
    setActionLoading(null);
  };

  const handleUnskip = async (person) => {
    setActionLoading(person.original_name);
    try {
      await unskipPersonFn(conversationId, person.original_name, person.entity_id || null);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Unskip failed', e); }
    setActionLoading(null);
  };

  const handleDismissPerson = async (person) => {
    setActionLoading(person.original_name);
    try {
      await dismissPersonFn(conversationId, person.original_name, person.entity_id || null);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Dismiss person failed', e); }
    setActionLoading(null);
  };

  const handleSearch = async (q) => {
    setLinkSearch(q);
    if (q.length < 2) { setLinkResults([]); return; }
    try {
      const results = await searchContactsFn(q, 10);
      setLinkResults(results.filter(c => c.is_confirmed !== 0));
    } catch { setLinkResults([]); }
  };

  const handleLink = async (person, targetId) => {
    setActionLoading(person.original_name);
    try {
      if (person.entity_id && person.is_provisional) {
        await linkProvisionalFn(person.entity_id, targetId);
      } else {
        // For auto_resolved "change" action, use confirm-person with new entity
        await confirmPersonFn(conversationId, person.original_name, targetId);
      }
      setLinkingName(null);
      setLinkSearch('');
      setLinkResults([]);
      fetchPeople();
      if (onResolved) onResolved();
      // Trigger text replace cascade if name mismatch detected
      const linkedContact = linkResults.find(c => c.id === targetId) || contacts.find(c => c.id === targetId);
      const newName = linkedContact ? (linkedContact.canonical_name || '').trim() : '';
      if (newName) {
        // Check all_names for any name that differs from the canonical name
        // (original_name may already be the canonical name due to alphabetic sorting)
        const allNames = person.all_names || [person.original_name];
        const mismatchedName = allNames.find(n => n && n.trim().toLowerCase() !== newName.toLowerCase());
        if (mismatchedName) {
          setTextReplaceTarget({ findText: mismatchedName.trim(), replaceWith: newName });
        }
      }
    } catch (e) { console.error('Link failed', e); }
    setActionLoading(null);
  };

  const handleDismiss = async (person) => {
    if (!person.entity_id) return;
    setActionLoading(person.original_name);
    try {
      await dismissProvisionalFn(person.entity_id);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Dismiss failed', e); }
    setActionLoading(null);
  };

  const handleLinkRemaining = async (person) => {
    if (!person.entity_id || !person.unlinked_claim_count) return;
    setActionLoading(person.original_name);
    try {
      await linkRemainingFn(conversationId, person.entity_id, person.canonical_name || person.original_name);
      fetchPeople();
      if (onResolved) onResolved();
    } catch (e) { console.error('Link remaining failed', e); }
    setActionLoading(null);
  };

  const startEdit = (person) => {
    setEditingName(person.original_name);
    setActionError(null);
    setEditForm({
      name: person.canonical_name || person.original_name || '',
      organization: '',
      title: '',
      email: '',
      phone: '',
      aliases: '',
      notes: '',
    });
  };

  const handleCreateContact = async (person) => {
    setActionLoading(person.original_name);
    setActionError(null);
    try {
      if (person.entity_id && person.is_provisional) {
        // Provisional contact: confirm with richer fields
        await confirmProvisionalFn(
          person.entity_id,
          editForm.name || null,
          false,
          null,
          editForm.email || null,
          editForm.phone || null,
          editForm.aliases || null,
        );
      } else {
        // Unresolved / no entity_id: create brand new contact
        const result = await api.createContact({
          canonical_name: editForm.name.trim(),
          original_name: person.original_name || undefined,
          organization: editForm.organization || undefined,
          title: editForm.title || undefined,
          email: editForm.email || undefined,
          phone: editForm.phone || undefined,
          aliases: editForm.aliases || undefined,
          notes: editForm.notes || undefined,
          push_to_networking_app: true,
          source_conversation_id: conversationId,
        });
        if (result && result.existing_id) {
          setActionError('A contact with that name already exists. Use Link to Existing instead.');
          setActionLoading(null);
          return;
        }
      }
      setEditingName(null);
      setActionError(null);
      fetchPeople();
      if (onResolved) onResolved();
      // Trigger text replace cascade if name mismatch detected
      const newName2 = (editForm.name || '').trim();
      if (newName2) {
        const allNames2 = person.all_names || [person.original_name];
        const mismatchedName2 = allNames2.find(n => n && n.trim().toLowerCase() !== newName2.toLowerCase());
        if (mismatchedName2) {
          setTextReplaceTarget({ findText: mismatchedName2.trim(), replaceWith: newName2 });
        }
      }
    } catch (e) {
      const msg = e.message || 'Create contact failed';
      if (msg.includes('409')) {
        setActionError('A contact with that name already exists. Use Link to Existing instead.');
      } else {
        setActionError(msg);
      }
      console.error('Create contact failed', e);
    }
    setActionLoading(null);
  };

  // Determine banner color based on state
  const bannerColor = allGreen ? C.success : (redPeople.length > 0 ? C.warning : C.warning);

  // Match pending routes to people in this conversation
  const pendingByName = {};
  (pendingEntitiesProp || []).forEach(pe => {
    const name = (pe.blocked_on_entity || '').toLowerCase();
    pendingByName[name] = pe.count;
  });
  const inputStyle = {
    width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4,
    background: C.bg, color: C.text, border: '1px solid ' + C.border,
    outline: 'none', boxSizing: 'border-box',
  };

  // All green collapsed state
  if (allGreen && !expanded) {
    return (
      <div style={{
        ...cardStyle, marginBottom: 16, cursor: 'pointer',
        borderColor: C.success + '44',
        background: C.success + '08',
      }} onClick={() => setExpanded(true)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{'\u{1F465}'}</span>
          <span style={{ color: C.success, fontWeight: 600, fontSize: 13 }}>
            {people.length} people {'\u2014'} all resolved {'\u2705'}
          </span>
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: 'auto' }}>click to expand</span>
        </div>
      </div>
    );
  }

  // Pending route badge helper for person rows
  const pendingBadgeFor = (person) => {
    const name = (person.canonical_name || person.original_name || '').toLowerCase();
    const count = pendingByName[name];
    if (!count) return null;
    return (
      <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, fontWeight: 600,
        background: '#7c3aed22', color: '#a78bfa', border: '1px solid #7c3aed44', marginLeft: 4 }}>
        {count} pending route{count !== 1 ? 's' : ''}
      </span>
    );
  };

  const renderStatusDot = (status) => {
    const color = status === 'confirmed' ? C.success : status === 'auto_resolved' ? C.warning : status === 'skipped' ? C.textDim : C.danger;
    return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />;
  };

  const renderPersonRow = (person) => {
    const isYellow = person.status === 'auto_resolved';
    const isRed = person.status === 'provisional' || person.status === 'unresolved';
    const isGreen = person.status === 'confirmed';
    const isSkipped = person.status === 'skipped';
    const isDismissed = person.status === 'dismissed';
    const isLoading = actionLoading === person.original_name;
    const isLinking = linkingName === person.original_name;
    const isEditing = editingName === person.original_name;

    return (
      <div key={person.original_name + (person.entity_id || '')} style={{
        padding: (isGreen || isSkipped || isDismissed) ? '6px 12px' : '10px 12px', marginBottom: 6,
        background: (isGreen || isSkipped || isDismissed) ? 'transparent' : C.card,
        borderRadius: 6,
        border: (isGreen || isSkipped || isDismissed) ? 'none' : '1px solid ' + C.border,
        opacity: isLoading ? 0.6 : (isSkipped || isDismissed) ? 0.5 : 1,
      }}>
        {isEditing ? (
          /* Create contact edit form — richer fields */
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Full Name *</label>
                <input value={editForm.name}
                  onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                  style={inputStyle} placeholder="First Last" />
              </div>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Organization</label>
                <input value={editForm.organization}
                  onChange={e => setEditForm(f => ({ ...f, organization: e.target.value }))}
                  style={inputStyle} placeholder="Company name" />
              </div>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Title</label>
                <input value={editForm.title}
                  onChange={e => setEditForm(f => ({ ...f, title: e.target.value }))}
                  style={inputStyle} placeholder="Job title" />
              </div>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Email</label>
                <input value={editForm.email}
                  onChange={e => setEditForm(f => ({ ...f, email: e.target.value }))}
                  style={inputStyle} placeholder="email@example.com" type="email" />
              </div>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Phone</label>
                <input value={editForm.phone}
                  onChange={e => setEditForm(f => ({ ...f, phone: e.target.value }))}
                  style={inputStyle} placeholder="(555) 123-4567" type="tel" />
              </div>
              <div>
                <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Aliases (semicolon-separated)</label>
                <input value={editForm.aliases}
                  onChange={e => setEditForm(f => ({ ...f, aliases: e.target.value }))}
                  style={inputStyle} placeholder="Nick; Nickname" />
              </div>
            </div>
            <div style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 11, color: C.textDim, display: 'block', marginBottom: 2 }}>Notes</label>
              <input value={editForm.notes}
                onChange={e => setEditForm(f => ({ ...f, notes: e.target.value }))}
                style={inputStyle} placeholder="Optional notes" />
            </div>
            {actionError && (
              <div style={{
                padding: '6px 10px', marginBottom: 8, fontSize: 12, borderRadius: 4,
                background: C.danger + '18', color: C.danger, border: '1px solid ' + C.danger + '33',
              }}>{actionError}</div>
            )}
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button onClick={() => handleCreateContact(person)}
                disabled={!editForm.name.trim() || actionLoading === person.original_name}
                style={{
                  padding: '5px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                  background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
                  opacity: editForm.name.trim() && actionLoading !== person.original_name ? 1 : 0.4,
                }}>{actionLoading === person.original_name ? 'Creating...' : 'Create Contact'}</button>
              <button onClick={() => { setEditingName(null); setActionError(null); }}
                style={{
                  padding: '5px 14px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                  background: C.card, color: C.textDim, border: '1px solid ' + C.border,
                }}>Cancel</button>
            </div>
          </div>
        ) : (
          /* Normal row */
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                {renderStatusDot(person.status)}
                <span style={{
                  color: (isGreen || isSkipped || isDismissed) ? C.textMuted : C.text,
                  fontWeight: (isGreen || isSkipped || isDismissed) ? 400 : 600,
                  fontSize: (isGreen || isSkipped || isDismissed) ? 12 : 14,
                }}>
                  {isGreen ? '\u2713 ' : isSkipped ? '\u23ED ' : isDismissed ? '\u2717 ' : ''}{person.canonical_name || person.original_name}
                </span>
                {isYellow && person.original_name !== person.canonical_name && (
                  <span style={{ color: C.textDim, fontSize: 11 }}>
                    (matched from "{person.original_name}")
                  </span>
                )}
                {isRed && (
                  <span style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 3, fontWeight: 600,
                    background: C.danger + '22', color: C.danger,
                  }}>
                    {person.status}
                  </span>
                )}
                {(person.claim_count > 0 && !isGreen || person.unlinked_claim_count > 0) && (
                  <span style={{ color: C.textDim, fontSize: 11 }}>
                    ({person.claim_count} claim{person.claim_count !== 1 ? 's' : ''}{person.unlinked_claim_count > 0 ? `, ${person.unlinked_claim_count} unlinked` : ''})
                  </span>
                )}
                {pendingBadgeFor(person)}
                {person.unlinked_claim_count > 0 && person.entity_id && (
                  <button onClick={() => handleLinkRemaining(person)} disabled={isLoading}
                    style={{
                      padding: '1px 6px', fontSize: 10, borderRadius: 3, cursor: 'pointer',
                      background: C.accent + '18', color: C.accent, border: '1px solid ' + C.accent + '33',
                      marginLeft: 2,
                    }}>Link {person.unlinked_claim_count}</button>
                )}
              </div>

              {/* Action buttons */}
              <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                {isYellow && (
                  <>
                    <button onClick={() => handleConfirm(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
                      }}>{'\u2713'} Confirm</button>
                    <button onClick={() => { setLinkingName(isLinking ? null : person.original_name); setLinkSearch(''); setLinkResults([]); }}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                      }}>Change</button>
                    <button onClick={() => handleSkip(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.card, color: C.textDim, border: '1px solid ' + C.border,
                      }}>{'\u2717'} Skip</button>
                  </>
                )}
                {isRed && person.status === 'provisional' && (
                  <>
                    <button onClick={() => { setLinkingName(isLinking ? null : person.original_name); setLinkSearch(''); setLinkResults([]); }}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                      }}>Link to Existing</button>
                    <button onClick={() => startEdit(person)}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
                      }}>Create Contact</button>
                    <button onClick={() => handleSkip(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.card, color: C.textDim, border: '1px solid ' + C.border,
                      }}>Skip</button>
                    <button onClick={() => handleDismissPerson(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.danger + '22', color: C.danger, border: '1px solid ' + C.danger + '44',
                      }}>Dismiss</button>
                  </>
                )}
                {isRed && person.status === 'unresolved' && (
                  <>
                    <button onClick={() => { setLinkingName(isLinking ? null : person.original_name); setLinkSearch(''); setLinkResults([]); }}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                      }}>Link to Existing</button>
                    <button onClick={() => startEdit(person)}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.success + '22', color: C.success, border: '1px solid ' + C.success + '44',
                      }}>Create Contact</button>
                    <button onClick={() => handleSkip(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.card, color: C.textDim, border: '1px solid ' + C.border,
                      }}>Skip</button>
                    <button onClick={() => handleDismissPerson(person)} disabled={isLoading}
                      style={{
                        padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                        background: C.danger + '22', color: C.danger, border: '1px solid ' + C.danger + '44',
                      }}>Dismiss</button>
                  </>
                )}
                {isSkipped && (
                  <button onClick={() => handleUnskip(person)} disabled={isLoading}
                    style={{
                      padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                      background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                    }}>Undo Skip</button>
                )}
                {isDismissed && (
                  <button onClick={() => handleUnskip(person)} disabled={isLoading}
                    style={{
                      padding: '3px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                      background: C.accent + '22', color: C.accent, border: '1px solid ' + C.accent + '44',
                    }}>Undo Dismiss</button>
                )}
              </div>
            </div>

            {/* Search dropdown for linking */}
            {isLinking && (
              <div style={{ marginTop: 8, padding: 8, background: C.bg, borderRadius: 4 }}>
                <input type="text" placeholder="Search contacts..."
                  value={linkSearch} onChange={e => handleSearch(e.target.value)}
                  autoFocus
                  style={{
                    width: '100%', padding: '6px 10px', fontSize: 13, borderRadius: 4,
                    background: C.card, color: C.text, border: '1px solid ' + C.border,
                    outline: 'none', boxSizing: 'border-box',
                  }} />
                {linkResults.length > 0 && (
                  <div style={{ marginTop: 4, maxHeight: 150, overflowY: 'auto' }}>
                    {linkResults.map(r => (
                      <div key={r.id}
                        onClick={() => handleLink(person, r.id)}
                        style={{
                          padding: '6px 10px', cursor: 'pointer', fontSize: 13,
                          color: C.text, borderRadius: 4,
                        }}
                        onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                        {r.canonical_name}
                        {r.email && <span style={{ color: C.textDim, marginLeft: 8, fontSize: 11 }}>{r.email}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  return (
    <div style={{
      ...cardStyle, marginBottom: 16,
      borderColor: bannerColor + '44',
      background: bannerColor + '08',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: allGreen ? 0 : 12 }}>
        <span style={{ fontSize: 14 }}>{'\u{1F465}'}</span>
        <span style={{ color: bannerColor, fontWeight: 600, fontSize: 14 }}>
          People ({people.length})
        </span>
        {yellowPeople.length > 0 && (
          <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3, background: C.warning + '22', color: C.warning }}>
            {yellowPeople.length} auto-resolved
          </span>
        )}
        {redPeople.length > 0 && (
          <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3, background: C.danger + '22', color: C.danger }}>
            {redPeople.length} needs attention
          </span>
        )}
        {allGreen && (
          <span style={{ color: C.textDim, fontSize: 11, cursor: 'pointer' }}
            onClick={() => setExpanded(false)}>
            {'\u2014'} all resolved {'\u2705'} (click to collapse)
          </span>
        )}
      </div>

      {/* Red people first (need attention) */}
      {redPeople.map(renderPersonRow)}

      {/* Yellow people (auto-resolved, need confirmation) */}
      {yellowPeople.map(renderPersonRow)}

      {/* Green people (compact) */}
      {(allGreen || expanded || greenPeople.length <= 3) && greenPeople.map(renderPersonRow)}
      {!allGreen && !expanded && greenPeople.length > 3 && (
        <div style={{ fontSize: 11, color: C.textDim, padding: '4px 12px', cursor: 'pointer' }}
          onClick={() => setExpanded(true)}>
          + {greenPeople.length} confirmed people (click to show)
        </div>
      )}

      {/* Skipped people */}
      {skippedPeople.map(renderPersonRow)}



      {/* Self at the bottom */}
      {selfPeople.map(person => (
        <div key="self" style={{ padding: '4px 12px', fontSize: 12, color: C.textDim }}>
          {'\u{1F464}'} {person.canonical_name || person.original_name} (you)
        </div>
      ))}
    </div>
  );
}


// ═══════════════════════════════════════════════════════
// ROUTING PREVIEW (Layer 3)
// ═══════════════════════════════════════════════════════
