import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { layout, colors } from '../styles';

const navItems = [
  { path: '/', label: 'Dashboard', icon: '\u229E' },
  { path: '/conversations', label: 'Conversations', icon: '\u25C9' },
  { path: '/search', label: 'Search', icon: '\u2315' },
  { path: '/people', label: 'People', icon: '\u2295' },
  { path: '/beliefs', label: 'Beliefs', icon: '\u25C7' },
  { path: '/pipeline', label: 'Pipeline', icon: '\u2699' },
  { path: '/triage', label: 'Triage', icon: '\u26A1' },
  { path: '/game-plans', label: 'Game Plans', icon: '\u25C8' },
  { path: '/performance', label: 'Performance', icon: '\u25C6' },
  { path: '/settings', label: 'Settings', icon: '\u2692' },
];

export default function Sidebar() {
  const location = useLocation();

  return (
    <nav style={layout.sidebar}>
      <div style={{
        padding: '20px 16px',
        borderBottom: `1px solid ${colors.border}`,
      }}>
        <div style={{
          fontSize: 20, fontWeight: 700, color: colors.accent, letterSpacing: '0.05em',
        }}>SAURON</div>
        <div style={{ fontSize: 11, color: colors.textDim, marginTop: 2 }}>
          Voice Intelligence v6
        </div>
      </div>

      <div style={{ flex: 1, padding: '12px 8px', overflowY: 'auto' }}>
        {navItems.map(item => {
          const isActive = item.path === '/'
            ? location.pathname === '/'
            : location.pathname.startsWith(item.path);

          return (
            <NavLink
              key={item.path}
              to={item.path}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 12px', borderRadius: 6, textDecoration: 'none',
                fontSize: 14,
                color: isActive ? colors.text : colors.textMuted,
                background: isActive ? 'rgba(59,130,246,0.12)' : 'transparent',
                borderLeft: isActive ? `3px solid ${colors.accent}` : '3px solid transparent',
                marginBottom: 2, transition: 'background 0.15s',
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = colors.cardHover; }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
            >
              <span style={{ fontSize: 16, width: 20, textAlign: 'center' }}>{item.icon}</span>
              {item.label}
            </NavLink>
          );
        })}
      </div>

      <div style={{
        padding: '12px 16px', borderTop: `1px solid ${colors.border}`,
        fontSize: 11, color: colors.textDim,
      }}>
        <StatusDot /> System Active
      </div>
    </nav>
  );
}

function StatusDot() {
  return (
    <span style={{
      display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
      background: colors.success, marginRight: 6, verticalAlign: 'middle',
    }} />
  );
}
