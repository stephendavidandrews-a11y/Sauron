import { NavLink } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { api } from '../api';

const navItems = [
  { path: '/', label: 'Today' },
  { path: '/prep', label: 'Prep' },
  { path: '/review', label: 'Review' },
  { path: '/search', label: 'Search' },
  { path: '/commitments', label: 'Commitments' },
  { path: '/learning', label: 'Learning' },
  { path: '/upload', label: 'Upload' },
];

export default function NavBar({ onCommandPalette, badgeCounts }) {
  const totalBadge = (badgeCounts?.speaker_review || 0) + (badgeCounts?.triage_review || 0) + (badgeCounts?.claim_review || 0);

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-card border-b border-border h-14 flex items-center px-4 md:px-8">
      <div className="font-bold text-accent tracking-wider text-lg mr-8 select-none">
        SAURON
      </div>

      <div className="flex gap-1">
        {navItems.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-accent/15 text-accent'
                  : 'text-text-muted hover:text-text hover:bg-card-hover'
              }`
            }
          >
            {item.label}
            {item.label === 'Review' && totalBadge > 0 && (
              <span style={{
                marginLeft: 4, fontSize: 10, padding: '1px 5px', borderRadius: 8,
                background: '#3b82f6', color: '#fff', fontWeight: 700, lineHeight: '14px',
              }}>{totalBadge}</span>
            )}
          </NavLink>
        ))}
      </div>

      <div className="flex-1" />

      <button
        onClick={onCommandPalette}
        className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm text-text-dim
                   border border-border hover:border-border-light hover:text-text-muted
                   transition-colors cursor-pointer bg-transparent"
      >
        <span className="text-xs font-mono">/</span>
        <span className="hidden md:inline">Command</span>
      </button>
    </nav>
  );
}
