/**
 * Tripwires — runtime detection of unexpected conditions.
 *
 * In development, these log warnings. In production, they silently track.
 * Call tripwire.check() after API calls to catch shape mismatches,
 * missing fields, unexpected types, and semantic anomalies.
 */

const isDev = import.meta.env.DEV;
const warnings = [];

function warn(category, message, context = {}) {
  const entry = {
    timestamp: new Date().toISOString(),
    category,
    message,
    ...context,
  };
  warnings.push(entry);
  if (warnings.length > 100) warnings.shift();
  if (isDev) {
    console.warn(`[TRIPWIRE:${category}] ${message}`, context);
  }
}

/**
 * Assert response shape matches expectations.
 * Does NOT throw — only warns.
 */
function assertShape(data, schema, label) {
  if (data === null || data === undefined) {
    warn('null_response', `${label}: response is ${data}`);
    return false;
  }

  for (const [key, type] of Object.entries(schema)) {
    if (type === 'required') {
      if (!(key in data)) {
        warn('missing_field', `${label}: missing required field ${key}`, { data });
        return false;
      }
    } else if (type === 'array') {
      if (key in data && !Array.isArray(data[key])) {
        warn('wrong_type', `${label}: ${key} expected array, got ${typeof data[key]}`, { data });
        return false;
      }
    } else if (type === 'number') {
      if (key in data && typeof data[key] !== 'number') {
        warn('wrong_type', `${label}: ${key} expected number, got ${typeof data[key]}`, { data });
        return false;
      }
    }
  }
  return true;
}

/**
 * Check for 200-OK responses that contain error indicators.
 */
function checkForSemantic200Error(data, label) {
  if (data && typeof data === 'object') {
    if ('error' in data) {
      warn('semantic_200_error', `${label}: 200 response contains error key`, { data });
      return true;
    }
    if (data.status === 'error') {
      warn('semantic_200_error', `${label}: 200 response has status=error`, { data });
      return true;
    }
  }
  return false;
}

/**
 * Detect list/detail inconsistency after a write.
 * Call with the written item and the list it should appear in.
 */
function checkWriteConsistency(writtenId, list, label) {
  if (!writtenId || !Array.isArray(list)) return;
  const found = list.some(item => item.id === writtenId);
  if (!found) {
    warn('write_inconsistency', `${label}: written item ${writtenId} not found in list after refresh`);
  }
}

/**
 * Global unhandled rejection catcher.
 * Installs once on import.
 */
if (typeof window !== 'undefined') {
  window.addEventListener('unhandledrejection', (event) => {
    warn('unhandled_rejection', `Unhandled promise rejection: ${event.reason?.message || event.reason}`, {
      stack: event.reason?.stack,
    });
  });
}

/**
 * Get all collected warnings (for dev panel).
 */
function getWarnings() {
  return [...warnings];
}

function clearWarnings() {
  warnings.length = 0;
}

export const tripwire = {
  assertShape,
  checkForSemantic200Error,
  checkWriteConsistency,
  warn,
  getWarnings,
  clearWarnings,
};
