/**
 * Shows when data was last loaded and provides a manual refresh button.
 * Turns amber after 5 minutes, red after 15 minutes.
 */
import { useState, useEffect } from 'react';

function timeSince(ts) {
  if (!ts) return 'never';
  const secs = Math.floor((Date.now() - ts) / 1000);
  if (secs < 5) return 'just now';
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

export default function FreshnessBar({ lastFetched, onRefresh, loading }) {
  const [, setTick] = useState(0);

  // Re-render every 10s to update the timestamp display
  useEffect(() => {
    const interval = setInterval(() => setTick(t => t + 1), 10000);
    return () => clearInterval(interval);
  }, []);

  const age = lastFetched ? Date.now() - lastFetched : Infinity;
  const stale = age > 5 * 60 * 1000;
  const veryStale = age > 15 * 60 * 1000;

  const color = veryStale ? '#f87171' : stale ? '#facc15' : '#6b7280';

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      fontSize: 11,
      color,
    }}>
      <span>
        {loading ? 'Refreshing...' : `Updated ${timeSince(lastFetched)}`}
      </span>
      {stale && !loading && (
        <span style={{ opacity: 0.7 }}>
          {veryStale ? '(data may be outdated)' : '(stale)'}
        </span>
      )}
      {onRefresh && !loading && (
        <button
          onClick={onRefresh}
          style={{
            background: 'none',
            border: `1px solid ${color}40`,
            borderRadius: 3,
            color,
            fontSize: 10,
            padding: '1px 6px',
            cursor: 'pointer',
          }}
        >
          Refresh
        </button>
      )}
    </div>
  );
}
