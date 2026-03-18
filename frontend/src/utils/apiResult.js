/**
 * Centralized API result handling.
 *
 * Wraps every API call to produce a typed result object:
 *   { ok, data, error, status, retryable, category }
 *
 * Categories:
 *   'success'       — 2xx with valid data
 *   'network'       — fetch failed (offline, DNS, timeout)
 *   'auth'          — 401/403
 *   'not_found'     — 404
 *   'validation'    — 422
 *   'rate_limited'  — 429
 *   'conflict'      — 409
 *   'server'        — 5xx
 *   'unknown'       — anything else
 */

const CATEGORY_MAP = {
  401: 'auth',
  403: 'auth',
  404: 'not_found',
  409: 'conflict',
  422: 'validation',
  429: 'rate_limited',
};

function categorize(status) {
  if (status >= 200 && status < 300) return 'success';
  if (CATEGORY_MAP[status]) return CATEGORY_MAP[status];
  if (status >= 500) return 'server';
  return 'unknown';
}

function isRetryable(category) {
  return ['network', 'server', 'rate_limited'].includes(category);
}

function parseStatus(errorMessage) {
  const match = errorMessage?.match(/^(\d{3}):/);
  return match ? parseInt(match[1], 10) : null;
}

/**
 * Wrap an API call (Promise) into a normalized result.
 *
 * Usage:
 *   const result = await safeCall(() => api.conversations(10, 0));
 *   if (!result.ok) { showError(result); return; }
 *   setData(result.data);
 */
export async function safeCall(fn) {
  try {
    const data = await fn();
    return {
      ok: true,
      data,
      error: null,
      status: 200,
      category: 'success',
      retryable: false,
    };
  } catch (err) {
    const status = parseStatus(err.message) || 0;
    const category = status ? categorize(status) : 'network';
    // Strip status prefix from message for display
    const message = status
      ? err.message.replace(/^\d{3}:\s*/, '').trim()
      : err.message || 'Network error — check your connection';

    return {
      ok: false,
      data: null,
      error: message,
      status,
      category,
      retryable: isRetryable(category),
    };
  }
}

/**
 * Human-friendly error messages by category.
 */
export function friendlyError(result) {
  if (result.ok) return null;
  switch (result.category) {
    case 'network': return 'Cannot reach Sauron — check if the server is running.';
    case 'auth': return 'Authentication failed — check API key.';
    case 'not_found': return 'Not found — this item may have been deleted.';
    case 'validation': return 'Invalid request — check your input.';
    case 'rate_limited': return 'Rate limited — wait a moment and retry.';
    case 'conflict': return 'Conflict — this item was modified by another action.';
    case 'server': return 'Server error — Sauron may need a restart.';
    default: return result.error || 'An unexpected error occurred.';
  }
}
