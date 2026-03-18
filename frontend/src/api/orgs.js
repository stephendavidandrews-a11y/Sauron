import { fetchJSON } from './client';

export async function fetchProvisionalOrgs(status = 'pending') {
  return fetchJSON(`/provisional-orgs?status=${status}`);
}

export async function approveProvisionalOrg(suggestionId, parentOrganizationId = null) {
  const body = parentOrganizationId ? { parentOrganizationId } : {};
  return fetchJSON(`/provisional-orgs/${suggestionId}/approve`, {
    method: 'POST', body: JSON.stringify(body),
  });
}

export async function mergeProvisionalOrg(suggestionId, targetOrgId) {
  return fetchJSON(`/provisional-orgs/${suggestionId}/merge`, {
    method: 'POST', body: JSON.stringify({ targetOrgId }),
  });
}

export async function dismissProvisionalOrg(suggestionId) {
  return fetchJSON(`/provisional-orgs/${suggestionId}/dismiss`, { method: 'POST' });
}

export async function searchNetworkingOrgs(query) {
  return fetchJSON(`/provisional-orgs/search-orgs?q=${encodeURIComponent(query)}`);
}
