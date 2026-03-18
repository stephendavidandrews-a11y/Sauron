import { fetchJSON } from './client';

export const beliefsApi = {
  beliefs: ({ limit = 50, status = null, topic = null, contactId = null, search = null } = {}) => {
    const params = new URLSearchParams({ limit });
    if (status) params.append('status', status);
    if (topic) params.append('topic', topic);
    if (contactId) params.append('contact_id', contactId);
    if (search) params.append('search', search);
    return fetchJSON(`/beliefs?${params}`);
  },
  beliefsByContact: (contactId, limit = 30) =>
    fetchJSON(`/beliefs/contact/${contactId}?limit=${limit}`),
  beliefsByTopic: (topic, limit = 20) =>
    fetchJSON(`/beliefs/topic/${encodeURIComponent(topic)}?limit=${limit}`),
  contestedBeliefs: (limit = 20) =>
    fetchJSON(`/beliefs/contested?limit=${limit}`),
  whatChanged: (entityType, entityId, days = 30) =>
    fetchJSON(`/beliefs/what-changed/${entityType}/${entityId}?days=${days}`),
  beliefEvidence: (beliefId) => fetchJSON(`/beliefs/${beliefId}/evidence`),
  beliefTransitions: (beliefId) => fetchJSON(`/beliefs/${beliefId}/transitions`),
  recentTransitions: (days = 14, limit = 100) =>
    fetchJSON(`/beliefs/transitions/recent?days=${days}&limit=${limit}`),
  beliefStats: () => fetchJSON('/beliefs/stats'),
  recentBeliefs: (days = 7, limit = 50) =>
    fetchJSON(`/beliefs/recent?days=${days}&limit=${limit}`),
  pendingResyntheses: () => fetchJSON('/beliefs/resynthesis/pending'),
  acceptResynthesis: (id) => fetchJSON(`/beliefs/resynthesis/${id}/accept`, { method: 'POST' }),
  rejectResynthesis: (id) => fetchJSON(`/beliefs/resynthesis/${id}/reject`, { method: 'POST' }),
  editResynthesis: (id, summary, status, confidence) =>
    fetchJSON(`/beliefs/resynthesis/${id}/edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ summary, status, confidence }),
    }),
};
