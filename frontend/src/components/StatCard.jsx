import React from 'react';
import { layout, colors } from '../styles';

export default function StatCard({ label, value, sub, color }) {
  return (
    <div style={{ ...layout.card, minWidth: 160 }}>
      <div style={{ fontSize: 12, color: colors.textMuted, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: color || colors.text }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: colors.textDim, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}
