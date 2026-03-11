import React from 'react';
import { colors } from '../styles';

export default function PageHeader({ title, subtitle }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, color: colors.text }}>{title}</h1>
      {subtitle && (
        <p style={{ fontSize: 13, color: colors.textMuted, marginTop: 4 }}>{subtitle}</p>
      )}
    </div>
  );
}
