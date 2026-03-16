import { useState } from 'react';
import { api } from '../../../api';
import { C } from '../styles';

export function CommitmentEditPanel({ claim, conversationId, onSave, onCancel }) {
  const [fields, setFields] = useState({
    firmness: claim.firmness || '',
    direction: claim.direction || '',
    has_specific_action: !!claim.has_specific_action,
    has_deadline: !!claim.has_deadline,
    time_horizon: claim.time_horizon || '',
    has_condition: !!claim.has_condition,
    condition_text: claim.condition_text || '',
  });
  const [feedback, setFeedback] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await api.correctClaimBatch(conversationId, claim.id, fields, feedback || null);
      onSave(result.claim || { ...claim, ...fields, review_status: 'user_corrected' });
    } catch (e) {
      console.error('Batch save failed', e);
    }
    setSaving(false);
  };

  const S = { label: { fontSize: 11, color: C.textMuted, marginBottom: 2, display: 'block' },
    select: { fontSize: 12, padding: '3px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%' },
    input: { fontSize: 12, padding: '3px 6px', borderRadius: 3, border: `1px solid ${C.border}`,
      background: C.cardBg || C.bg, color: C.text, width: '100%' },
    toggle: { display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12, color: C.text },
    row: { display: 'flex', gap: 12, flexWrap: 'wrap' },
    col: { flex: '1 1 140px', minWidth: 120 },
  };

  return (
    <div style={{ marginTop: 6, padding: '10px 12px', borderRadius: 6,
      background: C.warning + '08', border: `1px solid ${C.warning}40` }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.warning, marginBottom: 8 }}>
        Edit Commitment Fields
      </div>
      <div style={S.row}>
        <div style={S.col}>
          <label style={S.label}>Firmness</label>
          <select style={S.select} value={fields.firmness}
            onChange={e => setFields(p => ({ ...p, firmness: e.target.value }))}>
            <option value="">unclassified</option>
            <option value="required">required</option>
            <option value="concrete">concrete</option>
            <option value="intentional">intentional</option>
            <option value="tentative">tentative</option>
            <option value="social">social</option>
          </select>
        </div>
        <div style={S.col}>
          <label style={S.label}>Direction</label>
          <select style={S.select} value={fields.direction}
            onChange={e => setFields(p => ({ ...p, direction: e.target.value }))}>
            <option value="">unknown</option>
            <option value="owed_by_me">owed_by_me</option>
            <option value="owed_to_me">owed_to_me</option>
            <option value="owed_by_other">owed_by_other</option>
            <option value="mutual">mutual</option>
          </select>
        </div>
      </div>
      <div style={{ ...S.row, marginTop: 8 }}>
        <div style={S.col}>
          <label style={S.toggle}>
            <input type="checkbox" checked={fields.has_specific_action}
              onChange={e => setFields(p => ({ ...p, has_specific_action: e.target.checked }))} />
            Has specific action
          </label>
        </div>
        <div style={S.col}>
          <label style={S.toggle}>
            <input type="checkbox" checked={fields.has_deadline}
              onChange={e => setFields(p => ({ ...p, has_deadline: e.target.checked }))} />
            Has deadline
          </label>
        </div>
      </div>
      {fields.has_deadline && (
        <div style={{ marginTop: 6 }}>
          <label style={S.label}>Time Horizon</label>
          <input style={S.input} type="text" placeholder="e.g. 2026-03-15 or next week"
            value={fields.time_horizon}
            onChange={e => setFields(p => ({ ...p, time_horizon: e.target.value }))} />
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <label style={S.toggle}>
          <input type="checkbox" checked={fields.has_condition}
            onChange={e => setFields(p => ({ ...p, has_condition: e.target.checked }))} />
          Has condition
        </label>
      </div>
      {fields.has_condition && (
        <div style={{ marginTop: 4 }}>
          <label style={S.label}>Condition Text</label>
          <input style={S.input} type="text" placeholder="e.g. if budget is approved"
            value={fields.condition_text}
            onChange={e => setFields(p => ({ ...p, condition_text: e.target.value }))} />
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <label style={S.label}>Feedback (optional, for learning)</label>
        <textarea style={{ ...S.input, height: 40, resize: 'vertical' }}
          placeholder="Why are you making this change?"
          value={feedback} onChange={e => setFeedback(e.target.value)} />
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
        <button onClick={onCancel}
          style={{ fontSize: 11, padding: '4px 10px', borderRadius: 3,
            border: `1px solid ${C.border}`, background: 'transparent',
            color: C.textDim, cursor: 'pointer' }}>Cancel</button>
        <button onClick={handleSave} disabled={saving}
          style={{ fontSize: 11, padding: '4px 10px', borderRadius: 3, border: 'none',
            background: C.warning, color: '#fff', cursor: 'pointer',
            opacity: saving ? 0.6 : 1 }}>{saving ? 'Saving...' : 'Save'}</button>
      </div>
    </div>
  );
}

