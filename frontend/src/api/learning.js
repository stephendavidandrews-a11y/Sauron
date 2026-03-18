import { fetchJSON } from './client';

export const learningApi = {
  learningDashboard: () => fetchJSON('/learning/dashboard'),
  triggerLearningAnalysis: () =>
    fetchJSON('/learning/analyze', { method: 'POST' }),
  toggleAmendment: (id, active) =>
    fetchJSON(`/learning/amendments/${id}`, { method: 'PUT', body: JSON.stringify({ active }) }),
  editAmendment: (id, amendmentText) =>
    fetchJSON(`/learning/amendments/${id}`, { method: 'PATCH', body: JSON.stringify({ amendment_text: amendmentText }) }),
  contactPreferences: (contactId) =>
    fetchJSON(`/learning/contacts/${contactId}/preferences`),
  updateContactPreferences: (contactId, prefs) =>
    fetchJSON(`/learning/contacts/${contactId}/preferences`, { method: 'PUT', body: JSON.stringify(prefs) }),
};
