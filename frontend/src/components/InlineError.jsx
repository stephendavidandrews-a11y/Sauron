/**
 * Inline error display for sections that failed to load.
 * Shows category-aware message + optional retry button.
 */
import { friendlyError } from '../utils/apiResult';

export default function InlineError({ result, onRetry, label }) {
  if (!result || result.ok) return null;
  const message = label
    ? `${label}: ${friendlyError(result)}`
    : friendlyError(result);

  return (
    <div style={{
      background: 'rgba(239,68,68,0.08)',
      border: '1px solid rgba(239,68,68,0.2)',
      borderRadius: 8,
      padding: '10px 14px',
      fontSize: 13,
      color: '#f87171',
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    }}>
      <span style={{ flex: 1 }}>{message}</span>
      {result.retryable && onRetry && (
        <button onClick={onRetry} style={{
          background: 'none',
          border: '1px solid rgba(239,68,68,0.3)',
          borderRadius: 4,
          color: '#f87171',
          fontSize: 11,
          padding: '3px 10px',
          cursor: 'pointer',
        }}>Retry</button>
      )}
    </div>
  );
}
