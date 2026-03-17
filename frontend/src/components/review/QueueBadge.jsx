import React from 'react';

export function QueueBadge({ count, color }) {
  if (!count) return null;
  return (
    <span style={{
      fontSize: 12, padding: '2px 8px', borderRadius: 10,
      background: color + '33', color, fontWeight: 600,
    }}>{count}</span>
  );
}
