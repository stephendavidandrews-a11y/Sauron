import { fetchJSON, getCachedContacts } from './client';
export { clearContactsCache } from './client';

export const contactsApi = {
  graph: () => fetchJSON('/graph'),
  contacts: (limit = 500) => getCachedContacts(limit),
  searchContacts: (q, limit = 20) =>
    fetchJSON(`/graph/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  syncContacts: () => fetchJSON('/graph/sync-contacts', { method: 'POST' }),
  provisionalContacts: (limit = 50, conversationId = null) => {
    let url = `/graph/provisional?limit=${limit}`;
    if (conversationId) url += `&conversation_id=${conversationId}`;
    return fetchJSON(url);
  },
  linkProvisional: (contactId, targetContactId, feedback) =>
    fetchJSON(`/graph/provisional/${contactId}/link`, {
      method: 'POST',
      body: JSON.stringify({ target_contact_id: targetContactId, user_feedback: feedback }),
    }),
  confirmProvisional: (contactId, name, pushToNetworkingApp = false, feedback, email, phone, aliases) =>
    fetchJSON(`/graph/provisional/${contactId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ canonical_name: name || undefined, push_to_networking_app: pushToNetworkingApp, user_feedback: feedback || undefined, email: email || undefined, phone: phone || undefined, aliases: aliases || undefined }),
    }),
  dismissProvisional: (contactId) =>
    fetchJSON(`/graph/provisional/${contactId}/dismiss`, { method: 'POST' }),
  createContact: (data) =>
    fetchJSON('/graph/contacts', { method: 'POST', body: JSON.stringify(data) }),
  previewRename: (contactId, newName, oldNameOverride) =>
    fetchJSON(`/graph/contacts/${contactId}/preview-rename`, {
      method: 'POST',
      body: JSON.stringify({ new_name: newName, old_name_override: oldNameOverride || undefined }),
    }),
  applyRename: (contactId, newName, changeIds, oldNameOverride) =>
    fetchJSON(`/graph/contacts/${contactId}/apply-rename`, {
      method: 'POST',
      body: JSON.stringify({ new_name: newName, change_ids: changeIds, old_name_override: oldNameOverride || undefined }),
    }),
  previewTextReplace: (conversationId, findText, replaceWith) =>
    fetchJSON('/text-replace/preview', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, find_text: findText, replace_with: replaceWith }),
    }),
  applyTextReplace: (conversationId, findText, replaceWith, changeIds, editedChanges) =>
    fetchJSON('/text-replace/apply', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId, find_text: findText, replace_with: replaceWith, change_ids: changeIds, edited_changes: editedChanges || [] }),
    }),
  unresolvedRelational: (conversationId = null, limit = 50) => {
    let url = `/graph/unresolved-relational?limit=${limit}`;
    if (conversationId) url += `&conversation_id=${conversationId}`;
    return fetchJSON(url);
  },
  checkDuplicateContacts: () => fetchJSON("/graph/duplicates"),
  resolveDuplicateContacts: () => fetchJSON("/graph/resolve-duplicates", { method: "POST" }),
};
