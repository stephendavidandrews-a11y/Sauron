import { tripwire } from '../utils/tripwires';

const BASE = '/api';
const API_KEY = import.meta.env.VITE_SAURON_API_KEY || '';

export async function fetchJSON(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (API_KEY) { headers['X-API-Key'] = API_KEY; }
  const res = await fetch(`${BASE}${path}`, { headers, ...options });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  const data = await res.json();
  tripwire.checkForSemantic200Error(data, path);
  return data;
}

let _contactsCache = null;
let _contactsCacheTime = 0;
const CONTACTS_CACHE_TTL = 5 * 60 * 1000;

export function getCachedContacts(limit = 500) {
  if (_contactsCache && (Date.now() - _contactsCacheTime) < CONTACTS_CACHE_TTL) {
    return Promise.resolve(_contactsCache);
  }
  return fetchJSON(`/graph?limit=${limit}`).then(data => {
    _contactsCache = data;
    _contactsCacheTime = Date.now();
    return data;
  });
}

export function clearContactsCache() {
  _contactsCache = null;
  _contactsCacheTime = 0;
}

export { BASE, API_KEY };
