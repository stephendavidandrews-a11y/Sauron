import { useState } from 'react';
import { approveProvisionalOrg, mergeProvisionalOrg, dismissProvisionalOrg } from '../../../api';
import { C } from "../../../utils/colors";
import { OrgSearchDropdown } from './OrgSearchDropdown';

export function ProvisionalOrgCard({ group, onAction }) {
  const [acting, setActing] = useState(false);
  const [actionMode, setActionMode] = useState(null); // 'link' | 'sub-org'
  const [result, setResult] = useState(null);

  const firstSuggestion = group.suggestions[0];

  const handleCreate = async () => {
    setActing(true);
    try {
      const res = await approveProvisionalOrg(firstSuggestion.id);
      setResult({ type: 'success', message: `Created "${res.org_name}" (${res.org_id})` });
      onAction();
    } catch (e) {
      setResult({ type: 'error', message: e.message });
    }
    setActing(false);
  };

  const handleCreateSubOrg = async (parentOrg) => {
    setActing(true);
    try {
      const res = await approveProvisionalOrg(firstSuggestion.id, parentOrg.id);
      setResult({ type: 'success', message: `Created "${res.org_name}" under ${parentOrg.name}` });
      setActionMode(null);
      onAction();
    } catch (e) {
      setResult({ type: 'error', message: e.message });
    }
    setActing(false);
  };

  const handleLink = async (targetOrg) => {
    setActing(true);
    try {
      await mergeProvisionalOrg(firstSuggestion.id, targetOrg.id);
      setResult({ type: 'success', message: `Linked to "${targetOrg.name}"` });
      setActionMode(null);
      onAction();
    } catch (e) {
      setResult({ type: 'error', message: e.message });
    }
    setActing(false);
  };

  const handleDismiss = async () => {
    setActing(true);
    try {
      await dismissProvisionalOrg(firstSuggestion.id);
      setResult({ type: 'success', message: 'Dismissed' });
      onAction();
    } catch (e) {
      setResult({ type: 'error', message: e.message });
    }
    setActing(false);
  };

  if (result && result.type === 'success') {
    return (
      <div style={{ padding: '10px 14px', borderRadius: 6, border: `1px solid ${C.success}33`,
        background: C.success + '08', marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: C.success }}>{'\u2713'} {result.message}</span>
      </div>
    );
  }

  return (
    <div style={{ padding: '12px 14px', borderRadius: 6, border: `1px solid ${C.border}`,
      background: C.card, marginBottom: 8 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{group.display_name}</span>
          {group.count > 1 && (
            <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 10,
              background: C.accent + '22', color: C.accent }}>
              {group.count} mention{group.count !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        {group.suggested_by && group.suggested_by.length > 0 && (
          <span style={{ fontSize: 10, color: C.textDim }}>
            via {group.suggested_by.join(', ')}
          </span>
        )}
      </div>

      {/* Context from first suggestion */}
      {firstSuggestion.source_context && (
        <div style={{ fontSize: 12, color: C.textDim, marginBottom: 8, lineHeight: 1.4 }}>
          {firstSuggestion.source_context}
        </div>
      )}
      {firstSuggestion.resolution_source_context && (
        <div style={{ fontSize: 11, color: C.textDim, fontStyle: 'italic', marginBottom: 8 }}>
          Resolution: {firstSuggestion.resolution_source_context}
        </div>
      )}

      {/* Actions */}
      {!actionMode && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={handleCreate} disabled={acting}
            style={{ fontSize: 11, padding: '4px 10px', borderRadius: 4,
              border: `1px solid ${C.success}44`, background: C.success + '10',
              color: C.success, cursor: acting ? 'wait' : 'pointer' }}>
            + Create
          </button>
          <button onClick={() => setActionMode('sub-org')} disabled={acting}
            style={{ fontSize: 11, padding: '4px 10px', borderRadius: 4,
              border: `1px solid ${C.accent}44`, background: C.accent + '10',
              color: C.accent, cursor: acting ? 'wait' : 'pointer' }}>
            \u2514 Create as Sub-Org
          </button>
          <button onClick={() => setActionMode('link')} disabled={acting}
            style={{ fontSize: 11, padding: '4px 10px', borderRadius: 4,
              border: `1px solid ${C.purple}44`, background: C.purple + '10',
              color: C.purple, cursor: acting ? 'wait' : 'pointer' }}>
            \u2192 Link to Existing
          </button>
          <button onClick={handleDismiss} disabled={acting}
            style={{ fontSize: 11, padding: '4px 10px', borderRadius: 4,
              border: `1px solid ${C.danger}44`, background: 'transparent',
              color: C.danger, cursor: acting ? 'wait' : 'pointer', opacity: 0.8 }}>
            \u2717 Dismiss
          </button>
        </div>
      )}

      {/* Sub-org search */}
      {actionMode === 'sub-org' && (
        <OrgSearchDropdown
          placeholder="Search for parent organization..."
          onSelect={handleCreateSubOrg}
          onCancel={() => setActionMode(null)}
        />
      )}

      {/* Link/merge search */}
      {actionMode === 'link' && (
        <OrgSearchDropdown
          placeholder="Search for organization to link to..."
          onSelect={handleLink}
          onCancel={() => setActionMode(null)}
        />
      )}

      {result && result.type === 'error' && (
        <div style={{ marginTop: 6, fontSize: 11, color: C.danger }}>{result.message}</div>
      )}
    </div>
  );
}
