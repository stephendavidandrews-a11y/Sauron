import { fetchJSON } from './client';

export const conversationsApi = {
  conversations: (limit = 50, offset = 0) =>
    fetchJSON(`/conversations?limit=${limit}&offset=${offset}`),
  conversation: (id) => fetchJSON(`/conversations/${id}`),
  needsReview: (limit = 50) => fetchJSON(`/conversations/needs-review?limit=${limit}`),
  reviewQueue: () => fetchJSON('/conversations/review-queue'),
  markReviewed: (id) =>
    fetchJSON(`/conversations/${id}/review`, { method: 'POST' }),
  bulkReassign: (conversationId, fromEntityId, toEntityId, scope = 'all', dryRun = true) =>
    fetchJSON(`/conversations/${conversationId}/bulk-reassign`, {
      method: 'POST',
      body: JSON.stringify({ from_entity_id: fromEntityId, to_entity_id: toEntityId, scope, dry_run: dryRun }),
    }),
  editTranscript: (transcriptId, text) =>
    fetchJSON(`/conversations/transcripts/${transcriptId}`, {
      method: 'PATCH',
      body: JSON.stringify({ text }),
    }),
  queueCounts: () => fetchJSON('/conversations/queue-counts'),
  unreviewedClaims: (limit = 50) => fetchJSON(`/conversations/unreviewed-claims?limit=${limit}`),
  flagConversation: (id) =>
    fetchJSON(`/conversations/${id}/flag`, { method: 'PATCH' }),
  discardConversation: (id, reason) =>
    fetchJSON(`/conversations/${id}/discard`, {
      method: 'PATCH',
      body: JSON.stringify({ reason: reason || 'user_discarded' }),
    }),
  getAnnotations: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/annotations`),
  createAnnotation: (data) =>
    fetchJSON('/conversations/annotations', { method: 'POST', body: JSON.stringify(data) }),
  deleteAnnotation: (id) =>
    fetchJSON(`/conversations/annotations/${id}`, { method: 'DELETE' }),
  speakerMatches: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/speaker-matches`),
  triageData: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/triage`),
  conversationPeople: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/people`),
  confirmPerson: (conversationId, originalName, entityId) =>
    fetchJSON(`/conversations/${conversationId}/confirm-person`, {
      method: 'POST',
      body: JSON.stringify({ original_name: originalName, entity_id: entityId }),
    }),
  linkRemainingClaims: (conversationId, entityId, subjectName) =>
    fetchJSON(`/conversations/${conversationId}/link-remaining-claims`, {
      method: 'POST',
      body: JSON.stringify({ entity_id: entityId, subject_name: subjectName }),
    }),
  skipPerson: (conversationId, originalName, entityId) =>
    fetchJSON(`/conversations/${conversationId}/skip-person`, {
      method: 'POST',
      body: JSON.stringify({ original_name: originalName, entity_id: entityId }),
    }),
  unskipPerson: (conversationId, originalName, entityId) =>
    fetchJSON(`/conversations/${conversationId}/unskip-person`, {
      method: 'POST',
      body: JSON.stringify({ original_name: originalName, entity_id: entityId }),
    }),
  dismissPerson: (conversationId, originalName, entityId) =>
    fetchJSON(`/conversations/${conversationId}/dismiss-person`, {
      method: 'POST',
      body: JSON.stringify({ original_name: originalName, entity_id: entityId }),
    }),
  conversationEntities: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/entities`),
  routingPreview: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/routing-preview`),
};
