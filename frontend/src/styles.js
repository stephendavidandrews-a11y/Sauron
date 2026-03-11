// Shared styles — dark theme matching CFTC Command Center
export const colors = {
  bg: '#0a0f1a',
  card: '#111827',
  cardHover: '#1a2234',
  border: '#1f2937',
  borderLight: '#374151',
  text: '#e5e7eb',
  textMuted: '#9ca3af',
  textDim: '#6b7280',
  accent: '#3b82f6',
  accentHover: '#2563eb',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  purple: '#8b5cf6',
};

export const layout = {
  sidebar: {
    position: 'fixed',
    top: 0,
    left: 0,
    bottom: 0,
    width: 240,
    background: colors.card,
    borderRight: `1px solid ${colors.border}`,
    display: 'flex',
    flexDirection: 'column',
    zIndex: 100,
  },
  main: {
    marginLeft: 240,
    minHeight: '100vh',
    padding: '24px 32px',
  },
  card: {
    background: colors.card,
    border: `1px solid ${colors.border}`,
    borderRadius: 8,
    padding: 20,
  },
};
