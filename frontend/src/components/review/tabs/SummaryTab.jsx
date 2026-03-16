import { C, cardStyle, claimTypeColors } from '../styles';

export function SummaryTab({ synthesis, beliefUpdates, claims = [] }) {
  return (
    <div>
      {synthesis.summary && (
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Summary</h3>
          <p style={{ fontSize: 13, color: C.text, lineHeight: 1.6 }}>{synthesis.summary}</p>
        </div>
      )}
      {synthesis.vocal_intelligence_summary && (
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Vocal Intelligence</h3>
          <p style={{ fontSize: 13, color: C.text, lineHeight: 1.6 }}>{synthesis.vocal_intelligence_summary}</p>
        </div>
      )}
      {synthesis.topics_discussed?.length > 0 && (
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Topics</h3>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {synthesis.topics_discussed.map((t, i) => (
              <span key={i} style={{ fontSize: 12, padding: '4px 10px', borderRadius: 12,
                background: `${C.accent}15`, color: C.accent }}>{t}</span>
            ))}
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 16 }}>
        {(() => {
          const commitmentClaims = claims.filter(c => c.claim_type === 'commitment');
          const activeClaims = commitmentClaims.filter(c => c.review_status !== 'dismissed');
          const dismissedClaims = commitmentClaims.filter(c => c.review_status === 'dismissed');
          const iOwe = activeClaims.filter(c => c.direction === 'owed_by_me');
          const theyOwe = activeClaims.filter(c => c.direction === 'owed_to_me' || c.direction === 'owed_by_other');
          const otherActive = activeClaims.filter(c => !c.direction || (c.direction !== 'owed_by_me' && c.direction !== 'owed_to_me' && c.direction !== 'owed_by_other'));
          if (commitmentClaims.length === 0 && !synthesis.my_commitments?.length && !synthesis.contact_commitments?.length) return null;
          return (
            <div style={{ ...cardStyle, flex: 1 }}>
              <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Commitments</h3>
              {iOwe.map(c => <CommitmentRow key={c.id} claim={c} direction="I owe" />)}
              {theyOwe.map(c => <CommitmentRow key={c.id} claim={c} direction="They owe" />)}
              {otherActive.map(c => <CommitmentRow key={c.id} claim={c} direction="Commitment" />)}
              {dismissedClaims.length > 0 && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ fontSize: 11, color: C.textDim, cursor: 'pointer' }}>Dismissed ({dismissedClaims.length})</summary>
                  {dismissedClaims.map(c => <CommitmentRow key={c.id} claim={c} direction="Dismissed" isDismissed />)}
                </details>
              )}
            </div>
          );
        })()}
        {synthesis.follow_ups?.length > 0 && (
          <div style={{ ...cardStyle, flex: 1 }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Follow-ups</h3>
            {synthesis.follow_ups.map((f, i) => (
              <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}`, fontSize: 13 }}>
                <div style={{ color: C.text }}>{f.description}</div>
                {f.due_date && <div style={{ fontSize: 11, color: C.warning, marginTop: 2 }}>Due: {f.due_date}</div>}
              </div>
            ))}
          </div>
        )}
      </div>
      {beliefUpdates.length > 0 && (
        <div style={{ ...cardStyle, marginTop: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Belief Updates ({beliefUpdates.length})</h3>
          {beliefUpdates.map((b, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 11, padding: '2px 6px', borderRadius: 3,
                  background: `${C.success}22`, color: C.success }}>{b.status}</span>
                <span style={{ fontSize: 13, color: C.text }}>{b.belief_summary}</span>
              </div>
              {b.entity_name && (
                <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
                  {b.entity_name} &middot; {(b.confidence * 100).toFixed(0)}% confidence
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {synthesis.self_coaching?.length > 0 && (
        <div style={{ ...cardStyle, marginTop: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Self Coaching</h3>
          {synthesis.self_coaching.map((sc, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}`, fontSize: 13 }}>
              <div style={{ color: C.text }}>{sc.observation}</div>
              {sc.recommendation && <div style={{ fontSize: 12, color: C.accent, marginTop: 4 }}>&rarr; {sc.recommendation}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CommitmentRow({ claim, direction, isDismissed }) {
  const dirColor = direction === 'I owe' ? C.warning : direction === 'Dismissed' ? C.textDim : C.accent;
  const dirBg = direction === 'I owe' ? C.warning + '22' : direction === 'Dismissed' ? C.textDim + '15' : C.accent + '22';
  return (
    <div style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}`,
      opacity: isDismissed ? 0.4 : 1, textDecoration: isDismissed ? 'line-through' : 'none' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, fontWeight: 600,
          background: dirBg, color: dirColor, flexShrink: 0, marginTop: 2 }}>{direction}</span>
        <div style={{ flex: 1 }}>
          <span style={{ fontSize: 13, color: C.text }}>{claim.claim_text}</span>
          {(claim.firmness || claim.has_deadline || claim.has_condition || claim.has_specific_action) && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
              {claim.firmness && (
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                  background: C.warning + '15', color: C.warning }}>{claim.firmness}</span>
              )}
              {claim.has_specific_action && (
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                  background: C.accent + '15', color: C.accent }}>action</span>
              )}
              {claim.has_deadline && (
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                  background: C.success + '15', color: C.success }}>
                  deadline{claim.time_horizon && claim.time_horizon !== 'none' ? ': ' + claim.time_horizon : ''}
                </span>
              )}
              {claim.has_condition && (
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3,
                  background: '#8b5cf6' + '15', color: '#8b5cf6' }}>
                  conditional{claim.condition_text ? ': ' + claim.condition_text : ''}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function RawTab({ extraction }) {
  return (
    <div style={cardStyle}>
      <pre style={{ fontSize: 12, color: C.textMuted, whiteSpace: 'pre-wrap', lineHeight: 1.6, maxHeight: 600, overflow: 'auto' }}>
        {extraction ? JSON.stringify(extraction, null, 2) : 'No extraction data available.'}
      </pre>
    </div>
  );
}


