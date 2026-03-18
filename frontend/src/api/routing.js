import { fetchJSON } from './client';

export async function fetchRoutingSummary(conversationId) {
  try { return await fetchJSON(`/conversations/${conversationId}/routing-summary`); }
  catch { return []; }
}

export async function fetchPendingRoutes(by = "entity") {
  try { return await fetchJSON(`/routing/pending?by=${by}`); }
  catch { return []; }
}

export async function fetchGraphEdges(conversationId) {
  try { return await fetchJSON(`/graph-edges/conversation/${conversationId}`); }
  catch { return { edges: [], count: 0 }; }
}

export async function updateGraphEdge(edgeId, updates) {
  return fetchJSON(`/graph-edges/${edgeId}`, { method: 'PUT', body: JSON.stringify(updates) });
}

export async function confirmGraphEdge(edgeId) {
  return fetchJSON(`/graph-edges/${edgeId}/confirm`, { method: 'POST' });
}

export async function dismissGraphEdge(edgeId) {
  return fetchJSON(`/graph-edges/${edgeId}/dismiss`, { method: 'POST' });
}

export async function createGraphEdge(data) {
  return fetchJSON('/graph-edges', { method: 'POST', body: JSON.stringify(data) });
}
