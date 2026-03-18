import { fetchJSON, BASE, API_KEY } from './client';

export const searchApi = {
  search: (query, limit = 10, sourceType = null) => {
    let url = `/search?q=${encodeURIComponent(query)}&limit=${limit}`;
    if (sourceType) url += `&source_type=${sourceType}`;
    return fetchJSON(url);
  },
  unifiedSearch: (query, { limit = 20, contactId, dateFrom, dateTo, context } = {}) => {
    const params = new URLSearchParams({ q: query, limit });
    if (contactId) params.append('contact_id', contactId);
    if (dateFrom) params.append('date_from', dateFrom);
    if (dateTo) params.append('date_to', dateTo);
    if (context) params.append('context', context);
    return fetchJSON(`/search/unified?${params}`);
  },
  logSearchEvent: (data) => {
    const headers = { 'Content-Type': 'application/json' };
    if (API_KEY) headers['X-API-Key'] = API_KEY;
    fetch(`${BASE}/search/log`, {
      method: 'POST', headers, body: JSON.stringify(data),
    }).catch(() => {});
  },
};
