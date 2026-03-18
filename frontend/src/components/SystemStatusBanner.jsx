/**
 * System status banner — shows degraded/error state at top of app.
 * Polls /api/diagnostics/status every 60s.
 * Only visible when something is wrong.
 */
import { useState, useEffect } from 'react';
import { api } from '../api';

const POLL_INTERVAL = 60000;

export default function SystemStatusBanner() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const data = await fetch('/api/diagnostics/status', {
          headers: { 'X-API-Key': import.meta.env.VITE_SAURON_API_KEY || '' },
        }).then(r => r.json());
        if (mounted) setStatus(data);
      } catch {
        if (mounted) setStatus({ overall: 'unreachable' });
      }
    };
    check();
    const interval = setInterval(check, POLL_INTERVAL);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (!status || status.overall === 'healthy') return null;

  const issues = [];
  if (status.overall === 'unreachable') {
    issues.push('Sauron API is unreachable');
  } else {
    if (status.database?.status === 'error') issues.push('Database error');
    if (status.pipeline?.status === 'error') issues.push(`Pipeline: ${status.pipeline.failed} failed`);
    if (status.routing?.status === 'error') issues.push(`Routing: ${status.routing.failed} failed`);
    if (status.dependencies?.networking_app?.status === 'unreachable')
      issues.push('Networking App unreachable');
  }

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 10000,
      background: 'rgba(239, 68, 68, 0.12)',
      borderBottom: '1px solid rgba(239, 68, 68, 0.3)',
      padding: '6px 16px',
      fontSize: 12,
      color: '#f87171',
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    }}>
      <span style={{ fontWeight: 600 }}>System degraded</span>
      <span style={{ opacity: 0.8 }}>{issues.join(' \u2022 ')}</span>
      <span style={{ marginLeft: 'auto', opacity: 0.5 }}>
        Last check: {status.timestamp ? new Date(status.timestamp).toLocaleTimeString() : 'now'}
      </span>
    </div>
  );
}
