/**
 * Developer diagnostics panel — toggle with Ctrl+Shift+D.
 * Shows: tripwire warnings, system status, recent API calls.
 * Only renders in dev mode.
 */
import { useState, useEffect } from 'react';
import { tripwire } from '../utils/tripwires';

const isDev = import.meta.env.DEV;

export default function DevPanel() {
  const [open, setOpen] = useState(false);
  const [warnings, setWarnings] = useState([]);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    if (!isDev) return;
    const handler = (e) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        setOpen(o => !o);
        setWarnings(tripwire.getWarnings());
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    if (!open) return;
    setWarnings(tripwire.getWarnings());
    // Also fetch diagnostics
    fetch('/api/diagnostics/status', {
      headers: { 'X-API-Key': import.meta.env.VITE_SAURON_API_KEY || '' },
    })
      .then(r => r.json())
      .then(setStatus)
      .catch(() => setStatus({ overall: 'unreachable' }));
  }, [open]);

  if (!isDev || !open) return null;

  return (
    <div style={{
      position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 99999,
      background: '#0d1117', borderTop: '2px solid #30363d',
      maxHeight: '40vh', overflow: 'auto', padding: 16,
      fontFamily: 'monospace', fontSize: 12, color: '#c9d1d9',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontWeight: 700, color: '#58a6ff' }}>Dev Diagnostics (Ctrl+Shift+D)</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => { tripwire.clearWarnings(); setWarnings([]); }}
            style={{ background: 'none', border: '1px solid #30363d', color: '#8b949e', borderRadius: 3, padding: '2px 8px', cursor: 'pointer', fontSize: 11 }}>
            Clear
          </button>
          <button onClick={() => setOpen(false)}
            style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 14 }}>\u00d7</button>
        </div>
      </div>

      {/* System Status */}
      {status && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontWeight: 600, color: '#8b949e', marginBottom: 4 }}>System Status</div>
          <div style={{
            color: status.overall === 'healthy' ? '#3fb950' : status.overall === 'degraded' ? '#d29922' : '#f85149',
            fontWeight: 600,
          }}>
            {status.overall?.toUpperCase() || 'UNKNOWN'}
          </div>
          {status.pipeline && (
            <div style={{ color: '#8b949e' }}>
              Pipeline: {status.pipeline.pending || 0} pending, {status.pipeline.processing || 0} processing, {status.pipeline.failed || 0} failed
            </div>
          )}
          {status.routing && (
            <div style={{ color: '#8b949e' }}>
              Routing: {status.routing.failed || 0} failed, {status.routing.pending_entity || 0} pending
            </div>
          )}
          {status.dependencies?.networking_app && (
            <div style={{ color: status.dependencies.networking_app.status === 'ok' ? '#3fb950' : '#f85149' }}>
              Networking App: {status.dependencies.networking_app.status}
            </div>
          )}
        </div>
      )}

      {/* Tripwire Warnings */}
      <div style={{ fontWeight: 600, color: '#8b949e', marginBottom: 4 }}>
        Tripwire Warnings ({warnings.length})
      </div>
      {warnings.length === 0 ? (
        <div style={{ color: '#3fb950' }}>No warnings</div>
      ) : (
        <div>
          {warnings.map((w, i) => (
            <div key={i} style={{
              padding: '4px 8px', marginBottom: 2, borderRadius: 3,
              background: w.category.includes('error') ? 'rgba(248,81,73,0.1)' : 'rgba(210,153,34,0.1)',
              color: w.category.includes('error') ? '#f85149' : '#d29922',
            }}>
              <span style={{ opacity: 0.6 }}>[{w.category}]</span> {w.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
