import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { safeCall, friendlyError } from '../utils/apiResult';
import { useToast } from '../components/StatusToast';
import InlineError from '../components/InlineError';
import FreshnessBar from '../components/FreshnessBar';

// ── Constants ──────────────────────────────────────────────────────────

const FIRMNESS_ORDER = ['required', 'concrete', 'intentional', 'tentative', 'social'];

const FIRMNESS_COLORS = {
  required:    { bg: 'rgba(239, 68, 68, 0.15)',  text: '#f87171', border: 'rgba(239, 68, 68, 0.3)' },
  concrete:    { bg: 'rgba(249, 115, 22, 0.15)', text: '#fb923c', border: 'rgba(249, 115, 22, 0.3)' },
  intentional: { bg: 'rgba(59, 130, 246, 0.15)', text: '#60a5fa', border: 'rgba(59, 130, 246, 0.3)' },
  tentative:   { bg: 'rgba(156, 163, 175, 0.15)',text: '#9ca3af', border: 'rgba(156, 163, 175, 0.3)' },
  social:      { bg: 'rgba(107, 114, 128, 0.12)',text: '#6b7280', border: 'rgba(107, 114, 128, 0.25)' },
};

const STATUS_COLORS = {
  open:      { bg: 'rgba(59, 130, 246, 0.12)', text: '#60a5fa' },
  done:      { bg: 'rgba(34, 197, 94, 0.12)',  text: '#4ade80' },
  cancelled: { bg: 'rgba(107, 114, 128, 0.12)',text: '#6b7280' },
  deferred:  { bg: 'rgba(234, 179, 8, 0.12)',  text: '#facc15' },
};

function isOverdue(item) {
  if (!item.due_date || item.tracker_status !== 'open') return false;
  return item.due_date < new Date().toISOString().slice(0, 10);
}

function formatDate(d) {
  if (!d) return null;
  try {
    const date = new Date(d + 'T00:00:00');
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch { return d; }
}

function extractPersonName(item) {
  // For owed_by_me, the "to whom" is the other person (subject_name minus "Stephen Andrews")
  // For owed_to_me, the "from whom" is subject_name
  const name = item.subject_name;
  if (!name) return null;
  if (name.toLowerCase().includes('stephen andrews')) {
    // Try to find the other person from claim_text
    return null;
  }
  return name;
}

// ── Badge Component ────────────────────────────────────────────────────

function Badge({ children, color }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '1px 8px',
      borderRadius: 6,
      fontSize: 11,
      fontWeight: 600,
      background: color.bg,
      color: color.text,
      border: color.border ? `1px solid ${color.border}` : undefined,
      lineHeight: '18px',
      whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  );
}

// ── Stats Bar ──────────────────────────────────────────────────────────

function StatsBar({ stats }) {
  if (!stats) return null;
  const { i_owe, owed_to_me } = stats;
  return (
    <div className="flex gap-4 flex-wrap mb-6">
      <div className="bg-card border border-border rounded-lg px-5 py-3 flex-1 min-w-[220px]">
        <div className="text-xs text-text-dim uppercase tracking-wide mb-1">I Owe</div>
        <div className="flex items-center gap-3">
          {i_owe.overdue > 0 && (
            <span style={{ color: '#f87171', fontWeight: 700, fontSize: 14 }}>
              {i_owe.overdue} overdue
            </span>
          )}
          <span className="text-text-muted text-sm">{i_owe.open} open</span>
          <span className="text-text-dim text-sm">{i_owe.done} done</span>
        </div>
      </div>
      <div className="bg-card border border-border rounded-lg px-5 py-3 flex-1 min-w-[220px]">
        <div className="text-xs text-text-dim uppercase tracking-wide mb-1">Owed to Me</div>
        <div className="flex items-center gap-3">
          {owed_to_me.overdue > 0 && (
            <span style={{ color: '#fb923c', fontWeight: 700, fontSize: 14 }}>
              {owed_to_me.overdue} overdue
            </span>
          )}
          <span className="text-text-muted text-sm">{owed_to_me.open} pending</span>
          <span className="text-text-dim text-sm">{owed_to_me.done} received</span>
        </div>
      </div>
    </div>
  );
}

// ── Commitment Row ─────────────────────────────────────────────────────

function CommitmentRow({ item, onStatusChange }) {
  const [updating, setUpdating] = useState(false);
  const overdue = isOverdue(item);
  const person = extractPersonName(item);
  const firmColor = FIRMNESS_COLORS[item.firmness] || FIRMNESS_COLORS.tentative;

  const handleStatusChange = async (newStatus) => {
    setUpdating(true);
    try {
      await onStatusChange(item.id, newStatus);
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div
      style={{
        borderLeft: overdue ? '3px solid #ef4444' : '3px solid transparent',
        opacity: item.tracker_status === 'done' || item.tracker_status === 'cancelled' ? 0.5 : 1,
      }}
      className="bg-card border border-border rounded-lg px-4 py-3 mb-2 hover:border-border-light transition-colors"
    >
      <div className="flex items-start gap-3">
        {/* Checkbox for done */}
        <button
          onClick={() => handleStatusChange(item.tracker_status === 'done' ? 'open' : 'done')}
          disabled={updating}
          className="mt-0.5 flex-shrink-0"
          style={{
            width: 18, height: 18, borderRadius: 4,
            border: item.tracker_status === 'done' ? '2px solid #4ade80' : '2px solid #4b5563',
            background: item.tracker_status === 'done' ? 'rgba(34, 197, 94, 0.2)' : 'transparent',
            cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#4ade80', fontSize: 12, fontWeight: 700,
          }}
          title={item.tracker_status === 'done' ? 'Reopen' : 'Mark done'}
        >
          {item.tracker_status === 'done' ? '\u2713' : ''}
        </button>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <Badge color={firmColor}>{item.firmness || 'unknown'}</Badge>
            {overdue && <Badge color={{ bg: 'rgba(239, 68, 68, 0.2)', text: '#f87171' }}>OVERDUE</Badge>}
            {item.has_condition && (
              <span className="text-xs text-text-dim" title={item.condition_text}>
                conditional
              </span>
            )}
            {item.recurrence && (
              <span className="text-xs text-text-dim">
                {item.recurrence}
              </span>
            )}
          </div>

          <p className="text-sm text-text leading-snug mb-1" style={{
            textDecoration: item.tracker_status === 'done' ? 'line-through' : undefined,
          }}>
            {item.claim_text}
          </p>

          <div className="flex items-center gap-3 text-xs text-text-dim flex-wrap">
            {person && <span>{item.direction === 'owed_to_me' ? 'From' : 'To'}: <span className="text-text-muted">{person}</span></span>}
            {item.due_date && (
              <span style={{ color: overdue ? '#f87171' : undefined }}>
                Due: {formatDate(item.due_date)}
              </span>
            )}
            {!item.due_date && item.time_horizon && item.time_horizon !== 'none' && (
              <span>Horizon: {item.time_horizon}</span>
            )}
            {item.conversation_title && (
              <Link
                to={`/review/${item.conversation_id}`}
                className="hover:text-accent transition-colors"
                title="View source conversation"
              >
                {item.conversation_title}
              </Link>
            )}
            {!item.conversation_title && item.conversation_date && (
              <Link
                to={`/review/${item.conversation_id}`}
                className="hover:text-accent transition-colors"
              >
                {formatDate(item.conversation_date)}
              </Link>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {item.tracker_status === 'open' && (
            <>
              <button
                onClick={() => handleStatusChange('deferred')}
                disabled={updating}
                className="px-2 py-1 text-xs rounded text-text-dim hover:text-text-muted hover:bg-card-hover transition-colors"
                title="Defer"
              >
                Snooze
              </button>
              <button
                onClick={() => handleStatusChange('cancelled')}
                disabled={updating}
                className="px-2 py-1 text-xs rounded text-text-dim hover:text-red-400 hover:bg-card-hover transition-colors"
                title="Cancel"
              >
                Cancel
              </button>
            </>
          )}
          {(item.tracker_status === 'deferred' || item.tracker_status === 'cancelled') && (
            <button
              onClick={() => handleStatusChange('open')}
              disabled={updating}
              className="px-2 py-1 text-xs rounded text-text-dim hover:text-accent hover:bg-card-hover transition-colors"
            >
              Reopen
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Section (grouped by firmness for "owed to me") ─────────────────────

function FirmnessGroup({ firmness, items, onStatusChange, defaultExpanded }) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const color = FIRMNESS_COLORS[firmness] || FIRMNESS_COLORS.tentative;

  return (
    <div className="mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 mb-2 w-full text-left"
        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
      >
        <span style={{ color: color.text, fontSize: 13, fontWeight: 600, textTransform: 'capitalize' }}>
          {firmness || 'Unknown'}
        </span>
        <span className="text-text-dim text-xs">({items.length})</span>
        <span className="text-text-dim text-xs">{expanded ? '\u25BC' : '\u25B6'}</span>
      </button>
      {expanded && items.map(item => (
        <CommitmentRow key={item.id} item={item} onStatusChange={onStatusChange} />
      ))}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────

export default function Commitments() {
  const [tab, setTab] = useState('i_owe');
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('open');
  const [lastFetched, setLastFetched] = useState(null);
  const [firmnessFilter, setFirmnessFilter] = useState('');

  const [statsError, setStatsError] = useState(null);
  const [itemsError, setItemsError] = useState(null);
  const toast = useToast();

  const fetchStats = useCallback(async () => {
    const result = await safeCall(() => api.commitmentStats());
    if (result.ok) { setStats(result.data); setStatsError(null); }
    else setStatsError(result);
  }, []);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    const direction = tab === 'i_owe' ? 'owed_by_me,mutual' : 'owed_to_me,mutual';
    const result = await safeCall(() => api.commitments({ direction, status: statusFilter, firmness: firmnessFilter || undefined }));
    if (result.ok) { setItems(result.data); setItemsError(null); setLastFetched(Date.now()); }
    else { setItems([]); setItemsError(result); }
    setLoading(false);
  }, [tab, statusFilter, firmnessFilter]);

  useEffect(() => { fetchStats(); }, [fetchStats]);
  useEffect(() => { fetchItems(); }, [fetchItems]);

  const handleStatusChange = async (claimId, newStatus) => {
    const result = await safeCall(() => api.updateCommitmentStatus(claimId, newStatus));
    if (result.ok) {
      toast.success(`Commitment marked ${newStatus}`);
      fetchItems();
      fetchStats();
    } else {
      toast.error(friendlyError(result));
    }
  };

  // Group owed_to_me by firmness
  const groupedByFirmness = {};
  if (tab === 'owed_to_me') {
    for (const item of items) {
      const f = item.firmness || 'unknown';
      if (!groupedByFirmness[f]) groupedByFirmness[f] = [];
      groupedByFirmness[f].push(item);
    }
  }

  return (
    <div className="py-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-text">Commitments</h1>
        <FreshnessBar lastFetched={lastFetched} onRefresh={() => { fetchItems(); fetchStats(); }} loading={loading} />
      </div>

      <StatsBar stats={stats} />
      <InlineError result={statsError} onRetry={fetchStats} label="Stats" />
      <InlineError result={itemsError} onRetry={fetchItems} label="Commitments" />

      {/* Tab toggle */}
      <div className="flex items-center gap-1 mb-4 bg-card border border-border rounded-lg p-1 w-fit">
        <button
          onClick={() => setTab('i_owe')}
          className="px-4 py-1.5 rounded-md text-sm font-medium transition-colors"
          style={{
            background: tab === 'i_owe' ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
            color: tab === 'i_owe' ? '#60a5fa' : '#9ca3af',
          }}
        >
          I Owe
          {stats?.i_owe?.open > 0 && (
            <span style={{ marginLeft: 6, fontSize: 11, fontWeight: 700 }}>
              {stats.i_owe.open}
            </span>
          )}
        </button>
        <button
          onClick={() => setTab('owed_to_me')}
          className="px-4 py-1.5 rounded-md text-sm font-medium transition-colors"
          style={{
            background: tab === 'owed_to_me' ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
            color: tab === 'owed_to_me' ? '#60a5fa' : '#9ca3af',
          }}
        >
          Owed to Me
          {stats?.owed_to_me?.open > 0 && (
            <span style={{ marginLeft: 6, fontSize: 11, fontWeight: 700 }}>
              {stats.owed_to_me.open}
            </span>
          )}
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="bg-card border border-border rounded-md px-3 py-1.5 text-sm text-text-muted"
        >
          <option value="open">Open</option>
          <option value="done">Done</option>
          <option value="deferred">Deferred</option>
          <option value="cancelled">Cancelled</option>
          <option value="all">All</option>
        </select>
        <select
          value={firmnessFilter}
          onChange={e => setFirmnessFilter(e.target.value)}
          className="bg-card border border-border rounded-md px-3 py-1.5 text-sm text-text-muted"
        >
          <option value="">All firmness</option>
          <option value="required">Required</option>
          <option value="concrete">Concrete</option>
          <option value="intentional">Intentional</option>
          <option value="tentative">Tentative</option>
          <option value="social">Social</option>
        </select>
      </div>

      {/* Content */}
      {loading ? (
        <div className="text-text-dim text-sm py-8 text-center">Loading commitments...</div>
      ) : items.length === 0 ? (
        <div className="text-text-dim text-sm py-8 text-center">No commitments match these filters.</div>
      ) : tab === 'i_owe' ? (
        <div>
          {items.map(item => (
            <CommitmentRow key={item.id} item={item} onStatusChange={handleStatusChange} />
          ))}
        </div>
      ) : (
        <div>
          {FIRMNESS_ORDER.filter(f => groupedByFirmness[f]?.length > 0).map(f => (
            <FirmnessGroup
              key={f}
              firmness={f}
              items={groupedByFirmness[f]}
              onStatusChange={handleStatusChange}
              defaultExpanded={f === 'required' || f === 'concrete'}
            />
          ))}
          {groupedByFirmness['unknown']?.length > 0 && (
            <FirmnessGroup
              firmness="unknown"
              items={groupedByFirmness['unknown']}
              onStatusChange={handleStatusChange}
              defaultExpanded={false}
            />
          )}
        </div>
      )}
    </div>
  );
}
