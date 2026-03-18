import { fetchJSON } from './client';

export async function fetchTextPendingContacts() {
  return fetchJSON('/text/pending-contacts');
}

export async function approveTextContact(pendingId, { name, organization, title, email }) {
  return fetchJSON(`/text/pending-contacts/${pendingId}/approve`, {
    method: 'POST', body: JSON.stringify({ name, organization, title, email }),
  });
}

export async function dismissTextContact(pendingId) {
  return fetchJSON(`/text/pending-contacts/${pendingId}/dismiss`, { method: 'POST' });
}

export async function deferTextContact(pendingId) {
  return fetchJSON(`/text/pending-contacts/${pendingId}/defer`, { method: 'POST' });
}

export async function triggerTextSync(dryRun = false) {
  return fetchJSON(`/text/sync?dry_run=${dryRun}`, { method: 'POST' });
}

export async function fetchTextStatus() {
  return fetchJSON('/text/status');
}

export async function fetchTextThreads() {
  return fetchJSON('/text/threads');
}
