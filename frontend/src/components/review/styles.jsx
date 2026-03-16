// Design system constants for the review flow.

export const C = {
  bg: '#0a0f1a', card: '#111827', cardHover: '#1a2234',
  border: '#1f2937', borderLight: '#374151', text: '#e5e7eb',
  textMuted: '#9ca3af', textDim: '#6b7280', accent: '#3b82f6',
  success: '#10b981', warning: '#f59e0b', danger: '#ef4444', purple: '#8b5cf6',
  amber: '#d97706',
};
export const cardStyle = { background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20 };

export const claimTypeColors = {
  fact: C.accent, position: C.purple, commitment: C.warning,
  preference: C.success, relationship: '#ec4899', observation: C.textMuted, tactical: '#f97316',
};

export const errorTypes = [
  { value: 'hallucinated_claim', label: 'Not real / hallucinated' },
  { value: 'wrong_claim_type', label: 'Wrong type' },
  { value: 'wrong_modality', label: 'Wrong modality' },
  { value: 'wrong_polarity', label: 'Wrong polarity' },
  { value: 'wrong_confidence', label: 'Confidence too high/low' },
  { value: 'bad_commitment_extraction', label: 'Bad commitment' },
  { value: 'overstated_position', label: 'Overstated position' },
  { value: 'bad_entity_linking', label: 'Wrong person/entity' },
  { value: 'wrong_stability', label: 'Wrong stability' },
];



export const OBJECT_TYPE_LABELS = {
  standing_offers: 'Standing Offers',
  scheduling_leads: 'Scheduling Leads',
  graph_edges: 'Graph Edges',
  contact_commitments: 'Contact Commitments',
  policy_positions: 'Policy Positions',
  my_commitments: 'My Commitments',
  follow_ups: 'Follow-Ups',
};


// -- Graph Edge Review Banner --

export function Chip({ label, value, color }) {
  return (
    <span style={{ fontSize: 12, padding: '4px 10px', borderRadius: 4,
      background: `${color || C.accent}15`, color: C.textMuted }}>
      {label}: <strong style={{ color: color || C.text }}>{value}</strong>
    </span>
  );
}
