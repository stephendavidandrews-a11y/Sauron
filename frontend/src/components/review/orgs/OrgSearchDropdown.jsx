import { useState, useEffect, useCallback } from 'react';
import { searchNetworkingOrgs } from '../../../api';
import { C } from "../../../utils/colors";

export function OrgSearchDropdown({ onSelect, onCancel, placeholder }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  const doSearch = useCallback(async (q) => {
    if (q.length < 2) { setResults([]); return; }
    setSearching(true);
    try {
      const data = await searchNetworkingOrgs(q);
      setResults(Array.isArray(data) ? data : data.organizations || []);
    } catch (e) {
      console.error('Org search failed:', e);
      setResults([]);
    }
    setSearching(false);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => doSearch(query), 300);
    return () => clearTimeout(timer);
  }, [query, doSearch]);

  return (
    <div style={{ marginTop: 8, padding: 8, background: C.bg, border: `1px solid ${C.border}`,
      borderRadius: 6 }}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
        <input
          type="text" value={query} onChange={e => setQuery(e.target.value)}
          placeholder={placeholder || 'Search organizations...'}
          autoFocus
          style={{ flex: 1, fontSize: 12, padding: '4px 8px', borderRadius: 4,
            border: `1px solid ${C.border}`, background: C.card, color: C.text }}
        />
        <button onClick={onCancel}
          style={{ fontSize: 11, padding: '3px 8px', borderRadius: 3,
            border: `1px solid ${C.border}`, background: 'transparent',
            color: C.textDim, cursor: 'pointer' }}>Cancel</button>
      </div>
      {searching && <div style={{ fontSize: 11, color: C.textDim, padding: 4 }}>Searching...</div>}
      {results.length > 0 && (
        <div style={{ maxHeight: 150, overflowY: 'auto' }}>
          {results.map(org => (
            <div key={org.id} onClick={() => onSelect(org)}
              style={{ padding: '6px 8px', fontSize: 12, color: C.text, cursor: 'pointer',
                borderRadius: 4, display: 'flex', justifyContent: 'space-between' }}
              onMouseEnter={e => e.currentTarget.style.background = C.cardHover}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span>{org.name}</span>
              {org.industry && <span style={{ color: C.textDim, fontSize: 11 }}>{org.industry}</span>}
            </div>
          ))}
        </div>
      )}
      {query.length >= 2 && !searching && results.length === 0 && (
        <div style={{ fontSize: 11, color: C.textDim, padding: 4 }}>No organizations found</div>
      )}
    </div>
  );
}
