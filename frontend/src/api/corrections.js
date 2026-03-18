import { fetchJSON } from './client';

export const correctionsApi = {
  correctExtraction: (conversationId, correctionType, originalValue, correctedValue) =>
    fetchJSON('/correct/extraction', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, correction_type: correctionType, original_value: originalValue, corrected_value: correctedValue }),
    }),
  correctClaim: (conversationId, claimId, errorType, oldValue, newValue, feedback) =>
    fetchJSON('/correct/claim', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, claim_id: claimId, error_type: errorType, old_value: oldValue, new_value: newValue, user_feedback: feedback }),
    }),
  addClaim: (data) =>
    fetchJSON('/correct/add-claim', { method: 'POST', body: JSON.stringify(data) }),
  reassignClaim: (claimId, conversationId, episodeId) =>
    fetchJSON('/correct/reassign-claim', {
      method: 'PATCH',
      body: JSON.stringify({ claim_id: claimId, conversation_id: conversationId, episode_id: episodeId }),
    }),
  correctClaimBatch: (conversationId, claimId, corrections, feedback) =>
    fetchJSON('/correct/claim-batch', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, claim_id: claimId, corrections, user_feedback: feedback }),
    }),
  correctBelief: (beliefId, newStatus, feedback) =>
    fetchJSON('/correct/belief', {
      method: 'POST',
      body: JSON.stringify({ belief_id: beliefId, new_status: newStatus, user_feedback: feedback }),
    }),
  errorTypes: () => fetchJSON('/correct/error-types'),
  correctSpeaker: (conversationId, speakerLabel, correctContactId) =>
    fetchJSON('/correct/speaker', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, speaker_label: speakerLabel, correct_contact_id: correctContactId }),
    }),
  linkEntity: (conversationId, claimId, contactId, oldSubjectName, feedback) =>
    fetchJSON('/correct/entity-link', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, claim_id: claimId, contact_id: contactId, old_subject_name: oldSubjectName, user_feedback: feedback }),
    }),
  removeEntityLink: (linkId) =>
    fetchJSON(`/correct/entity-link/${linkId}`, { method: 'DELETE' }),
  saveRelationship: (anchorContactId, relationship, targetContactId, targetName, notes) =>
    fetchJSON('/correct/save-relationship', {
      method: 'POST',
      body: JSON.stringify({ anchor_contact_id: anchorContactId, relationship, target_contact_id: targetContactId, target_name: targetName, notes: notes || undefined }),
    }),
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
      body: JSON.stringify({ conversation_id: conversationId, claim_id: claimId, error_type: errorType, user_feedback: feedback }),
    }),
  updateCommitmentMeta: (conversationId, claimId, updates) =>
    fetchJSON('/correct/commitment-meta', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, claim_id: claimId, ...updates }),
    }),
  mergeSpeakers: (conversationId, fromLabel, toLabel) =>
    fetchJSON('/correct/merge-speakers', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, from_label: fromLabel, to_label: toLabel }),
    }),
  reassignSegment: (transcriptSegmentId, newSpeakerLabel) =>
    fetchJSON('/correct/reassign-segment', {
      method: 'POST',
      body: JSON.stringify({ transcript_segment_id: transcriptSegmentId, new_speaker_label: newSpeakerLabel }),
    }),
};
