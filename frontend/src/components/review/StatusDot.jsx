import React from 'react';

const statusText = { green: 'Processed', amber: 'Pending', red: 'Error', gray: 'Unknown' };

export function StatusDot({ color }) {
  return (
    <span role="status" aria-label={statusText[color] || color} style={{ color, fontSize: 10 }}>
      {'●'}
    </span>
  );
}
