const BASE = '/api';

async function fetchJSON(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  // Health
  health: () => fetchJSON('/health'),

  // Conversations
  conversations: (limit = 50, offset = 0) =>
    fetchJSON(`/conversations?limit=${limit}&offset=${offset}`),
  conversation: (id) => fetchJSON(`/conversations/${id}`),
  needsReview: (limit = 50) => fetchJSON(`/conversations/needs-review?limit=${limit}`),
  markReviewed: (id) =>
    fetchJSON(`/conversations/${id}/review`, { method: 'POST' }),

  // Bulk reassignment
  bulkReassign: (conversationId, fromEntityId, toEntityId, scope = 'all', dryRun = true) =>
    fetchJSON(`/conversations/${conversationId}/bulk-reassign`, {
      method: 'POST',
      body: JSON.stringify({
        from_entity_id: fromEntityId,
        to_entity_id: toEntityId,
        scope,
        dry_run: dryRun,
      }),
    }),

  // Transcript editing
  editTranscript: (transcriptId, text) =>
    fetchJSON(`/conversations/transcripts/${transcriptId}`, {
      method: 'PATCH',
      body: JSON.stringify({ text }),
    }),

  // Search
  search: (query, limit = 10, sourceType = null) => {
    let url = `/search?query=${encodeURIComponent(query)}&limit=${limit}`;
    if (sourceType) url += `&source_type=${sourceType}`;
    return fetchJSON(url);
  },

  // Graph / Contacts
  graph: () => fetchJSON('/graph'),
  contacts: (limit = 500) => fetchJSON(`/graph?limit=${limit}`),
  searchContacts: (q, limit = 20) =>
    fetchJSON(`/graph/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  syncContacts: () => fetchJSON('/graph/sync-contacts', { method: 'POST' }),

  // Provisional contacts
  provisionalContacts: (limit = 50, conversationId = null) => {
    let url = `/graph/provisional?limit=${limit}`;
    if (conversationId) url += `&conversation_id=${conversationId}`;
    return fetchJSON(url);
  },
  linkProvisional: (contactId, targetContactId, feedback) =>
    fetchJSON(`/graph/provisional/${contactId}/link`, {
      method: 'POST',
      body: JSON.stringify({
        target_contact_id: targetContactId,
        user_feedback: feedback,
      }),
    }),
  confirmProvisional: (contactId, name, pushToNetworkingApp = false, feedback, email, phone, aliases) =>
    fetchJSON(`/graph/provisional/${contactId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({
        canonical_name: name || undefined,
        push_to_networking_app: pushToNetworkingApp,
        user_feedback: feedback || undefined,
        email: email || undefined,
        phone: phone || undefined,
        aliases: aliases || undefined,
      }),
    }),
  dismissProvisional: (contactId) =>
    fetchJSON(`/graph/provisional/${contactId}/dismiss`, { method: 'POST' }),

  createContact: (data) =>
    fetchJSON('/graph/contacts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Performance
  performance: () => fetchJSON('/performance'),

  // Intentions
  intentions: () => fetchJSON('/intentions'),
  createIntention: (data) =>
    fetchJSON('/intentions', { method: 'POST', body: JSON.stringify(data) }),

  // Amendments
  amendments: () => fetchJSON('/amendments'),

  // Baselines
  baselines: () => fetchJSON('/baselines'),

  // Voice profiles
  profiles: () => fetchJSON('/voice-profiles'),

  // Brief
  brief: (contactId) => fetchJSON(`/brief/${contactId}`),
  todayBrief: () => fetchJSON('/brief/today'),
  personBrief: (contactId) => fetchJSON(`/brief/person/${contactId}`),
  personBriefByName: (name) => fetchJSON(`/brief/person/by-name/${encodeURIComponent(name)}`),

  // Pipeline (v6)
  pipelineStatus: () => fetchJSON('/pipeline/status'),
  pipelineIngest: (source = null) =>
    fetchJSON(`/pipeline/ingest${source ? `?source=${source}` : ''}`, { method: 'POST' }),
  pipelineProcess: (conversationId) =>
    fetchJSON(`/pipeline/process/${conversationId}`, { method: 'POST' }),
  pipelineProcessPending: () =>
    fetchJSON('/pipeline/process-pending', { method: 'POST' }),

  // Routing status
  routingStatus: () => fetchJSON('/pipeline/routing-status'),

  // Beliefs (v6)
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

  // Learning
  learningDashboard: () => fetchJSON('/learning/dashboard'),
  triggerLearningAnalysis: () =>
    fetchJSON('/learning/analyze', { method: 'POST' }),
  toggleAmendment: (id, active) =>
    fetchJSON(`/learning/amendments/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ active }),
    }),
  editAmendment: (id, amendmentText) =>
    fetchJSON(`/learning/amendments/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ amendment_text: amendmentText }),
    }),
  contactPreferences: (contactId) =>
    fetchJSON(`/learning/contacts/${contactId}/preferences`),
  updateContactPreferences: (contactId, prefs) =>
    fetchJSON(`/learning/contacts/${contactId}/preferences`, {
      method: 'PUT',
      body: JSON.stringify(prefs),
    }),

  // Corrections
  correctExtraction: (conversationId, correctionType, originalValue, correctedValue) =>
    fetchJSON('/correct/extraction', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: conversationId,
        correction_type: correctionType,
        original_value: originalValue,
        corrected_value: correctedValue,
      }),
    }),
  correctClaim: (conversationId, claimId, errorType, oldValue, newValue, feedback) =>
    fetchJSON('/correct/claim', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: conversationId,
        claim_id: claimId,
        error_type: errorType,
        old_value: oldValue,
        new_value: newValue,
        user_feedback: feedback,
      }),
    }),
  addClaim: (data) =>
    fetchJSON('/correct/add-claim', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  reassignClaim: (claimId, conversationId, episodeId) =>
    fetchJSON('/correct/reassign-claim', {
      method: 'PATCH',
      body: JSON.stringify({
        claim_id: claimId,
        conversation_id: conversationId,
        episode_id: episodeId,
      }),
    }),
  correctClaimBatch: (conversationId, claimId, corrections, feedback) =>
    fetchJSON('/correct/claim-batch', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: conversationId,
        claim_id: claimId,
        corrections,
        user_feedback: feedback,
      }),
    }),
  correctBelief: (beliefId, newStatus, feedback) =>
    fetchJSON('/correct/belief', {
      method: 'POST',
      body: JSON.stringify({
        belief_id: beliefId,
        new_status: newStatus,
        user_feedback: feedback,
      }),
    }),
  errorTypes: () => fetchJSON('/correct/error-types'),
  correctSpeaker: (conversationId, speakerLabel, correctContactId) =>
    fetchJSON('/correct/speaker', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: conversationId,
        speaker_label: speakerLabel,
        correct_contact_id: correctContactId,
      }),
    }),
  linkEntity: (conversationId, claimId, contactId, oldSubjectName, feedback) =>
    fetchJSON('/correct/entity-link', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: conversationId,
        claim_id: claimId,
        contact_id: contactId,
        old_subject_name: oldSubjectName,
        user_feedback: feedback,
      }),
    }),
  removeEntityLink: (linkId) =>
    fetchJSON(`/correct/entity-link/${linkId}`, { method: 'DELETE' }),
  saveRelationship: (anchorContactId, relationship, targetContactId, targetName, notes) =>
    fetchJSON('/correct/save-relationship', {
      method: 'POST',
      body: JSON.stringify({
        anchor_contact_id: anchorContactId,
        relationship,
        target_contact_id: targetContactId,
        target_name: targetName,
        notes: notes || undefined,
      }),
    }),
  // Claim approval
  approveClaim: (conversationId, claimId) =>
    fetchJSON('/correct/approve-claim', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, claim_id: claimId }),
    }),
  approveClaimsBulk: (conversationId, claimIds) =>
    fetchJSON('/correct/approve-claims-bulk', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, claim_ids: claimIds }),
    }),
  deferClaim: (conversationId, claimId, reason) =>
    fetchJSON('/correct/defer-claim', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, claim_id: claimId, reason }),
    }),
  dismissClaim: (conversationId, claimId, errorType, feedback) =>
    fetchJSON('/correct/dismiss-claim', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: conversationId,
        claim_id: claimId,
        error_type: errorType,
        user_feedback: feedback,
      }),
    }),

  // Commitment metadata
  updateCommitmentMeta: (conversationId, claimId, updates) =>
    fetchJSON('/correct/commitment-meta', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, claim_id: claimId, ...updates }),
    }),


  // Pipeline queue management (Deploy 2)
  queueCounts: () => fetchJSON('/conversations/queue-counts'),
  unreviewedClaims: (limit = 50) => fetchJSON(`/conversations/unreviewed-claims?limit=${limit}`),
  flagConversation: (id) =>
    fetchJSON(`/conversations/${id}/flag`, { method: 'PATCH' }),
  discardConversation: (id, reason) =>
    fetchJSON(`/conversations/${id}/discard`, {
      method: 'PATCH',
      body: JSON.stringify({ reason: reason || 'user_discarded' }),
    }),
  confirmSpeakers: (conversationId) =>
    fetchJSON(`/pipeline/confirm-speakers/${conversationId}`, { method: 'POST' }),
  promoteTriage: (conversationId) =>
    fetchJSON(`/pipeline/promote-triage/${conversationId}`, { method: 'POST' }),
  archiveTriage: (conversationId) =>
    fetchJSON(`/pipeline/archive-triage/${conversationId}`, { method: 'POST' }),

  // Audio (Deploy 2)
  audioClipUrl: (conversationId, start, end) =>
    `/api/audio/${conversationId}/clip?start=${start}&end=${end}`,
  speakerSampleUrl: (conversationId, label) =>
    `/api/audio/${conversationId}/speaker-sample/${label}`,

  // Annotations (Deploy 2)
  getAnnotations: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/annotations`),
  createAnnotation: (data) =>
    fetchJSON('/conversations/annotations', { method: 'POST', body: JSON.stringify(data) }),
  deleteAnnotation: (id) =>
    fetchJSON(`/conversations/annotations/${id}`, { method: 'DELETE' }),

  // Speaker review data (Deploy 2)
  speakerMatches: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/speaker-matches`),
  triageData: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/triage`),

  // Speaker operations (Deploy 2)
  mergeSpeakers: (conversationId, fromLabel, toLabel) =>
    fetchJSON('/correct/merge-speakers', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: conversationId,
        from_label: fromLabel,
        to_label: toLabel,
      }),
    }),
  reassignSegment: (transcriptSegmentId, newSpeakerLabel) =>
    fetchJSON('/correct/reassign-segment', {
      method: 'POST',
      body: JSON.stringify({
        transcript_segment_id: transcriptSegmentId,
        new_speaker_label: newSpeakerLabel,
      }),
    }),

  unresolvedRelational: (conversationId = null, limit = 50) => {
    let url = `/graph/unresolved-relational?limit=${limit}`;
    if (conversationId) url += `&conversation_id=${conversationId}`;
    return fetchJSON(url);
  },

  // Unified search (v2)
  unifiedSearch: (query, { limit = 20, contactId, dateFrom, dateTo, context } = {}) => {
    const params = new URLSearchParams({ q: query, limit });
    if (contactId) params.append('contact_id', contactId);
    if (dateFrom) params.append('date_from', dateFrom);
    if (dateTo) params.append('date_to', dateTo);
    if (context) params.append('context', context);
    return fetchJSON(`/search/unified?${params}`);
  },

  // Search telemetry
  logSearchEvent: (data) => {
    fetch(`${BASE}/search/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).catch(() => {}); // fire and forget
  },

  // Belief re-synthesis proposals (Feature 1)
  pendingResyntheses: () => fetchJSON('/beliefs/resynthesis/pending'),
  acceptResynthesis: (id) => fetchJSON(`/beliefs/resynthesis/${id}/accept`, { method: 'POST' }),
  rejectResynthesis: (id) => fetchJSON(`/beliefs/resynthesis/${id}/reject`, { method: 'POST' }),
  editResynthesis: (id, summary, status, confidence) =>
    fetchJSON(`/beliefs/resynthesis/${id}/edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ summary, status, confidence }),
    }),

  // Phase 3b: People review & routing preview
  conversationPeople: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/people`),

  confirmPerson: (conversationId, originalName, entityId) =>
    fetchJSON(`/conversations/${conversationId}/confirm-person`, {
      method: 'POST',
      body: JSON.stringify({ original_name: originalName, entity_id: entityId }),
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

  // Contact duplicate detection
  checkDuplicateContacts: () =>
    fetchJSON("/graph/duplicates"),

  resolveDuplicateContacts: () =>
    fetchJSON("/graph/resolve-duplicates", { method: "POST" }),

  routingPreview: (conversationId) =>
    fetchJSON(`/conversations/${conversationId}/routing-preview`),
};
