import { fetchJSON } from './client';

export const miscApi = {
  health: () => fetchJSON('/health'),
  performance: () => fetchJSON('/performance'),
  intentions: () => fetchJSON('/intentions'),
  createIntention: (data) =>
    fetchJSON('/intentions', { method: 'POST', body: JSON.stringify(data) }),
  amendments: () => fetchJSON('/amendments'),
  baselines: () => fetchJSON('/baselines'),
  profiles: () => fetchJSON('/voice-profiles'),
  brief: (contactId) => fetchJSON(`/brief/${contactId}`),
  todayBrief: () => fetchJSON('/brief/today'),
  personBrief: (contactId) => fetchJSON(`/brief/person/${contactId}`),
  personBriefByName: (name) => fetchJSON(`/brief/person/by-name/${encodeURIComponent(name)}`),
  commitments: ({ direction, status, firmness, contact, limit } = {}) => {
    const params = new URLSearchParams();
    if (direction) params.append("direction", direction);
    if (status) params.append("status", status);
    if (firmness) params.append("firmness", firmness);
    if (contact) params.append("contact", contact);
    if (limit) params.append("limit", limit);
    return fetchJSON(`/commitments?${params}`);
  },
  commitmentStats: () => fetchJSON("/commitments/stats"),
  updateCommitmentStatus: (claimId, trackerStatus, snoozedUntil) =>
    fetchJSON(`/commitments/${claimId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ tracker_status: trackerStatus, snoozed_until: snoozedUntil || null }),
    }),
  entityList: (entityType = null, confirmed = null) => {
    const params = new URLSearchParams();
    if (entityType) params.append('entity_type', entityType);
    if (confirmed !== null) params.append('confirmed', confirmed);
    return fetchJSON(`/entities?${params}`);
  },
  entityDetail: (entityId) => fetchJSON(`/entities/${entityId}`),
  confirmEntity: (entityId) =>
    fetchJSON(`/entities/${entityId}/confirm`, { method: 'POST' }),
  dismissEntity: (entityId) =>
    fetchJSON(`/entities/${entityId}/dismiss`, { method: 'POST' }),
  mergeEntities: (keeperId, otherId) =>
    fetchJSON(`/entities/merge`, {
      method: 'POST',
      body: JSON.stringify({ keeper_id: keeperId, other_id: otherId }),
    }),
  updateEntity: (entityId, updates) =>
    fetchJSON(`/entities/${entityId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    }),
};
