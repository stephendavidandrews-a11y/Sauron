import { useState } from 'react';
import { api } from '../../../api';
import { C } from "../../../utils/colors";

export function EntityChips({ claim, contacts, onLink, onRemoveEntity, conversationId }) {
  const entities = claim.entities || [];
  const [showAdd, setShowAdd] = useState(false);
  const [search, setSearch] = useState('');
  const [results, setResults] = useState([]);

  const handleSearch = async (q) => {
    setSearch(q);
    if (q.length < 2) { setResults([]); return; }
    try {
      const r = await api.searchContacts(q, 10);
      setResults(r.filter(c => c.is_confirmed !== 0));
    } catch { setResults(contacts.filter(c => c.is_confirmed !== 0 && c.canonical_name.toLowerCase().includes(q.toLowerCase())).slice(0, 10)); }
  };

  // Fallback: if no entities from junction table, show subject_name with link button
  const hasEntities = entities.length > 0;
  const subjectName = claim.linked_entity_name || claim.subject_name;

  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', position: 'relative' }}>
      {hasEntities ? (
        <>
          {entities.map(ent => {
            const isObject = ent.entity_table === 'unified_entities';
            const typeColors = {
              organization: { color: '#f59e0b', border: '#f59e0b44', icon: '\u{1F3E2}' },
              legislation: { color: '#8b5cf6', border: '#8b5cf644', icon: '\u{1F4DC}' },
              topic: { color: '#06b6d4', border: '#06b6d444', icon: '\u{1F3F7}' },
            };
            const tc = isObject ? (typeColors[ent.entity_type] || { color: C.textMuted, border: C.border, icon: '\u{1F4CC}' }) : null;
            const chipColor = isObject ? tc.color : C.success;
            const chipBorder = isObject ? tc.border : `${C.success}44`;
            const chipIcon = isObject ? tc.icon : '\u{1F517}';
            return (
              <span key={ent.id} style={{
                fontSize: 11, padding: '1px 6px', borderRadius: 3, display: 'inline-flex',
                alignItems: 'center', gap: 3,
                border: `1px solid ${chipBorder}`, color: chipColor,
              }}>
                {chipIcon} {ent.entity_name}
                {isObject && ent.entity_type && (
                  <span style={{ fontSize: 9, color: chipColor, opacity: 0.7, marginLeft: 1 }}>
                    [{ent.entity_type}]
                  </span>
                )}
                {ent.role !== 'subject' && (
                  <span style={{ fontSize: 9, color: C.textDim, marginLeft: 2 }}>({ent.role})</span>
                )}
                {ent.link_source === 'user' && (
                  <span style={{ fontSize: 9, color: C.accent }} title="User-linked">*</span>
                )}
                {onRemoveEntity && (
                  <button onClick={(e) => { e.stopPropagation(); onRemoveEntity(claim, ent.id); }}
                    style={{ fontSize: 9, color: C.textDim, cursor: 'pointer', background: 'none',
                      border: 'none', padding: '0 2px', lineHeight: 1 }}
                    title="Remove entity link" aria-label="Remove entity link">&times;</button>
                )}
              </span>
            );
          })}
        </>
      ) : subjectName ? (
        <button onClick={() => setShowAdd(!showAdd)}
          style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3,
            border: `1px solid ${C.warning}44`, background: 'transparent',
            color: C.warning, cursor: 'pointer' }}>
          {'\u{1F50D}'} {subjectName}
        </button>
      ) : null}

      {/* Add entity button */}
      <button onClick={() => setShowAdd(!showAdd)}
        style={{ fontSize: 11, padding: '1px 5px', borderRadius: 3,
          border: `1px solid ${C.border}`, background: 'transparent',
          color: C.textDim, cursor: 'pointer', lineHeight: 1 }}
        title="Add entity link" aria-label="Add entity link">+</button>

      {/* Search dropdown */}
      {showAdd && (
        <div style={{ position: 'absolute', left: 0, top: '100%', marginTop: 4, zIndex: 50,
          background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, padding: 8,
          minWidth: 260, boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
          <input value={search} onChange={e => handleSearch(e.target.value)} placeholder="Search contacts..."
            autoFocus style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: C.bg,
              border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, marginBottom: 6, outline: 'none' }} />
          <div style={{ maxHeight: 200, overflow: 'auto' }}>
            {results.map(c => (
              <button key={c.id} onClick={() => { onLink(claim, c.id); setShowAdd(false); setSearch(''); setResults([]); }}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 8px',
                  fontSize: 12, color: C.text, background: 'transparent', border: 'none', cursor: 'pointer', borderRadius: 4 }}
                onMouseEnter={e => e.target.style.background = C.cardHover}
                onMouseLeave={e => e.target.style.background = 'transparent'}>
                {c.canonical_name}
                {c.email && <span style={{ color: C.textDim, marginLeft: 6 }}>{c.email}</span>}
              </button>
            ))}
            {search.length >= 2 && results.length === 0 && (
              <p style={{ fontSize: 12, color: C.textDim, padding: 6 }}>No matches</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Legacy wrapper for backward compatibility

// ═══════════════════════════════════════════════════════
// ERROR TYPE DROPDOWN
