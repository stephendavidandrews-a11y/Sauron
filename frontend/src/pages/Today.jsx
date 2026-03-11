import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';

// ── Utilities ──────────────────────────────────────────────────────────

function getTimeMode() {
  return new Date().getHours() < 13 ? 'morning' : 'evening';
}

function relativeTime(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  if (diffMs < 0) return 'just now';
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatDuration(seconds) {
  if (!seconds) return null;
  const m = Math.round(seconds / 60);
  if (m < 1) return '<1 min';
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem > 0 ? `${h}h ${rem}m` : `${h}h`;
}

function formatDate() {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

// ── Reusable card components ───────────────────────────────────────────

function Card({ title, badge, action, children, className = '' }) {
  return (
    <div className={`bg-card border border-border rounded-lg p-5 ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide">
            {title}
          </h3>
          {badge != null && (
            <span className="text-xs font-bold bg-accent/20 text-accent px-2 py-0.5 rounded-full">
              {badge}
            </span>
          )}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function Empty({ message }) {
  return <p className="text-sm text-text-dim italic">{message}</p>;
}

function StatusChip({ status }) {
  const map = {
    active: 'bg-success/20 text-success',
    refined: 'bg-success/20 text-success',
    provisional: 'bg-warning/20 text-warning',
    qualified: 'bg-warning/20 text-warning',
    time_bounded: 'bg-warning/20 text-warning',
    contested: 'bg-danger/20 text-danger',
    stale: 'bg-border text-text-dim',
    superseded: 'bg-border text-text-dim',
    under_review: 'bg-warning/30 text-warning',
  };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium whitespace-nowrap ${map[status] || 'bg-border text-text-dim'}`}>
      {status?.replace('_', ' ') || 'unknown'}
    </span>
  );
}

function ProcessingChip({ status }) {
  const map = {
    completed: 'bg-success/20 text-success',
    processing: 'bg-accent/20 text-accent',
    pending: 'bg-warning/20 text-warning',
    error: 'bg-danger/20 text-danger',
    transcribing: 'bg-warning/20 text-warning',
    awaiting_speaker_review: 'bg-purple-400/20 text-purple-400',
    triaging: 'bg-warning/20 text-warning',
    triage_rejected: 'bg-warning/20 text-warning',
    extracting: 'bg-accent/20 text-accent',
    awaiting_claim_review: 'bg-accent/20 text-accent',
  };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${map[status] || 'bg-border text-text-dim'}`}>
      {status || 'unknown'}
    </span>
  );
}

function ShowMoreButton({ expanded, count, onClick }) {
  if (count <= 0) return null;
  return (
    <button
      onClick={onClick}
      className="mt-2 text-xs text-accent hover:text-accent-hover transition-colors cursor-pointer bg-transparent border-0 p-0"
    >
      {expanded ? 'Show less' : `Show ${count} more`}
    </button>
  );
}

function useExpandable(items, defaultCount = 5) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? items : items.slice(0, defaultCount);
  const remaining = items.length - defaultCount;
  const toggle = useCallback(() => setExpanded(e => !e), []);
  return { visible, expanded, remaining, toggle };
}

// ── Section cards ──────────────────────────────────────────────────────

function NeedsReviewCard({ count }) {
  return (
    <Card title="Needs review" badge={count > 0 ? count : null}>
      {count > 0 ? (
        <div className="flex items-center gap-4">
          <span className="text-3xl font-bold text-accent">{count}</span>
          <div className="flex-1">
            <span className="text-sm text-text-muted">
              conversation{count !== 1 ? 's' : ''} ready for review
            </span>
          </div>
          <Link
            to="/review"
            className="text-sm text-accent hover:text-accent-hover transition-colors font-medium"
          >
            Quick Pass &rarr;
          </Link>
        </div>
      ) : (
        <Empty message="Nothing needs review. All caught up." />
      )}
    </Card>
  );
}

function WhatChangedCard({ beliefs }) {
  const { visible, expanded, remaining, toggle } = useExpandable(beliefs, 5);

  return (
    <Card title="What changed">
      {beliefs.length > 0 ? (
        <>
          <ul className="space-y-2.5">
            {visible.map((b, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-text">
                    {b.entity_name || 'Unknown'}
                  </span>
                  <span className="text-text-dim mx-1.5">&middot;</span>
                  <span className="text-text-muted">
                    {b.belief_summary?.length > 100
                      ? b.belief_summary.slice(0, 100) + '...'
                      : b.belief_summary}
                  </span>
                  {b.confidence != null && (
                    <span className="text-text-dim text-xs ml-1.5">
                      {Math.round(b.confidence * 100)}%
                    </span>
                  )}
                </div>
                <StatusChip status={b.status} />
                {b.last_changed_at && (
                  <span className="text-xs text-text-dim whitespace-nowrap shrink-0">
                    {relativeTime(b.last_changed_at)}
                  </span>
                )}
              </li>
            ))}
          </ul>
          <ShowMoreButton expanded={expanded} count={remaining} onClick={toggle} />
        </>
      ) : (
        <Empty message="No major changes overnight." />
      )}
    </Card>
  );
}

function CommitmentsCard({ mine, theirs }) {
  const [tab, setTab] = useState('mine');
  const items = tab === 'mine' ? mine : theirs;
  const { visible, expanded, remaining, toggle } = useExpandable(items, 5);

  const totalCount = mine.length + theirs.length;

  return (
    <Card
      title="Open commitments"
      badge={totalCount > 0 ? totalCount : null}
    >
      {totalCount > 0 ? (
        <>
          <div className="flex gap-1 mb-3">
            <button
              onClick={() => setTab('mine')}
              className={`px-3 py-1 text-xs rounded font-medium cursor-pointer border-0 transition-colors ${
                tab === 'mine'
                  ? 'bg-accent text-white'
                  : 'bg-card-hover text-text-muted hover:text-text'
              }`}
            >
              I owe ({mine.length})
            </button>
            <button
              onClick={() => setTab('theirs')}
              className={`px-3 py-1 text-xs rounded font-medium cursor-pointer border-0 transition-colors ${
                tab === 'theirs'
                  ? 'bg-accent text-white'
                  : 'bg-card-hover text-text-muted hover:text-text'
              }`}
            >
              They owe ({theirs.length})
            </button>
          </div>

          {items.length > 0 ? (
            <>
              <ul className="space-y-3">
                {visible.map((c, i) => (
                  <li key={i} className="text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <span className="text-text">{c.claim_text}</span>
                        {c.subject_name && (
                          <span className="text-accent text-xs ml-1.5">
                            &mdash; {c.subject_name}
                          </span>
                        )}
                      </div>
                      {c.confidence != null && (
                        <span className="text-text-dim text-xs shrink-0">
                          {Math.round(c.confidence * 100)}%
                        </span>
                      )}
                    </div>
                    {c.evidence_quote && (
                      <div className="text-xs text-text-dim mt-1 pl-3 border-l-2 border-border italic">
                        {c.evidence_quote.length > 120
                          ? c.evidence_quote.slice(0, 120) + '...'
                          : c.evidence_quote}
                      </div>
                    )}
                    {c.captured_at && (
                      <div className="text-xs text-text-dim mt-0.5">
                        {relativeTime(c.captured_at)}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              <ShowMoreButton expanded={expanded} count={remaining} onClick={toggle} />
            </>
          ) : (
            <Empty
              message={tab === 'mine' ? 'Nothing you owe right now.' : 'No outstanding items from others.'}
            />
          )}
        </>
      ) : (
        <Empty message="No open commitments tracked." />
      )}
    </Card>
  );
}

function TodayConversationsCard({ conversations }) {
  const { visible, expanded, remaining, toggle } = useExpandable(conversations, 5);

  return (
    <Card title="Today's conversations" badge={conversations.length > 0 ? conversations.length : null}>
      {conversations.length > 0 ? (
        <>
          <ul className="space-y-2">
            {visible.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 text-sm">
                <Link
                  to={`/conversations/${c.id}`}
                  className="text-text hover:text-accent transition-colors truncate"
                >
                  {c.manual_note || c.title || `${c.source || 'unknown'} capture`}
                  {c.duration_seconds ? (
                    <span className="text-text-dim ml-1.5">
                      ({formatDuration(c.duration_seconds)})
                    </span>
                  ) : null}
                </Link>
                <div className="flex items-center gap-2 shrink-0">
                  <ProcessingChip status={c.processing_status} />
                  <span className="text-xs text-text-dim">
                    {relativeTime(c.captured_at)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
          <ShowMoreButton expanded={expanded} count={remaining} onClick={toggle} />
        </>
      ) : (
        <Empty message="No conversations captured today yet." />
      )}
    </Card>
  );
}

function UnresolvedSpeakersCard({ speakers }) {
  if (!speakers || speakers.length === 0) return null;

  return (
    <Card title="Unresolved speakers" badge={speakers.length}>
      <div className="flex items-center gap-3">
        <span className="text-2xl font-bold text-warning">{speakers.length}</span>
        <span className="text-sm text-text-muted flex-1">
          speaker{speakers.length !== 1 ? 's' : ''} could not be matched to a contact
        </span>
        <Link
          to="/review"
          className="text-sm text-accent hover:text-accent-hover transition-colors font-medium"
        >
          Resolve &rarr;
        </Link>
      </div>
      <ul className="mt-3 space-y-1.5">
        {speakers.slice(0, 5).map((s, i) => (
          <li key={i} className="flex items-center justify-between text-sm">
            <span className="text-text font-mono text-xs">{s.speaker_label}</span>
            <span className="text-text-dim text-xs">{relativeTime(s.captured_at)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function WhatHappenedCard({ conversations }) {
  const { visible, expanded, remaining, toggle } = useExpandable(conversations, 7);

  return (
    <Card title="What happened today" badge={conversations.length > 0 ? conversations.length : null}>
      {conversations.length > 0 ? (
        <>
          <ul className="space-y-2.5">
            {visible.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 text-sm">
                <Link
                  to={`/conversations/${c.id}`}
                  className="text-text hover:text-accent transition-colors flex-1 min-w-0 truncate"
                >
                  {c.source || 'unknown'}
                  {c.duration_seconds ? ` \u2014 ${formatDuration(c.duration_seconds)}` : ''}
                </Link>
                <div className="flex items-center gap-3 shrink-0 text-xs text-text-dim">
                  {c.episode_count > 0 && (
                    <span>{c.episode_count} episode{c.episode_count !== 1 ? 's' : ''}</span>
                  )}
                  {c.claim_count > 0 && (
                    <span>{c.claim_count} claim{c.claim_count !== 1 ? 's' : ''}</span>
                  )}
                  <ProcessingChip status={c.processing_status} />
                </div>
              </li>
            ))}
          </ul>
          <ShowMoreButton expanded={expanded} count={remaining} onClick={toggle} />
        </>
      ) : (
        <Empty message="No conversations captured today." />
      )}
    </Card>
  );
}

function StillNeedsActionCard({ reviewCount, speakers }) {
  const speakerCount = speakers?.length || 0;
  const total = reviewCount + speakerCount;

  if (total === 0) {
    return (
      <Card title="Still needs action">
        <Empty message="Everything is handled. Nothing pending." />
      </Card>
    );
  }

  return (
    <Card title="Still needs action" badge={total}>
      <div className="space-y-3">
        {reviewCount > 0 && (
          <div className="flex items-center justify-between">
            <div className="text-sm text-text">
              <span className="font-bold text-accent">{reviewCount}</span>
              <span className="text-text-muted ml-1.5">
                conversation{reviewCount !== 1 ? 's' : ''} awaiting review
              </span>
            </div>
            <Link
              to="/review"
              className="text-xs text-accent hover:text-accent-hover transition-colors"
            >
              Review &rarr;
            </Link>
          </div>
        )}
        {speakerCount > 0 && (
          <div className="flex items-center justify-between">
            <div className="text-sm text-text">
              <span className="font-bold text-warning">{speakerCount}</span>
              <span className="text-text-muted ml-1.5">
                unresolved speaker{speakerCount !== 1 ? 's' : ''}
              </span>
            </div>
            <Link
              to="/review"
              className="text-xs text-accent hover:text-accent-hover transition-colors"
            >
              Resolve &rarr;
            </Link>
          </div>
        )}
      </div>
    </Card>
  );
}

function ContestedBeliefsCard({ beliefs }) {
  if (!beliefs || beliefs.length === 0) return null;

  return (
    <Card title="Contested beliefs" badge={beliefs.length}>
      <ul className="space-y-2.5">
        {beliefs.map((b, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            <span className="text-danger mt-0.5 shrink-0">&#9679;</span>
            <div className="flex-1 min-w-0">
              <span className="font-medium text-text">{b.entity_name || 'Unknown'}</span>
              <span className="text-text-dim mx-1">&middot;</span>
              <span className="text-text-muted">
                {b.belief_summary?.length > 120
                  ? b.belief_summary.slice(0, 120) + '...'
                  : b.belief_summary}
              </span>
            </div>
            <StatusChip status={b.status} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

function PipelineStatusBar({ pending, processing }) {
  if (pending === 0 && processing === 0) return null;

  return (
    <div className="flex items-center gap-4 bg-card border border-border rounded-lg px-4 py-2.5 text-xs">
      {processing > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
          <span className="text-text-muted">
            {processing} processing
          </span>
        </div>
      )}
      {pending > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-warning" />
          <span className="text-text-muted">
            {pending} pending
          </span>
        </div>
      )}
    </div>
  );
}

function RoutingStatusBar({ routing }) {
  if (!routing) return null;
  const { failed_count = 0, pending_entity_count = 0, sent_count = 0 } = routing;
  if (failed_count === 0 && pending_entity_count === 0) return null;

  return (
    <div className="flex items-center gap-4 bg-card border border-border rounded-lg px-4 py-2.5 text-xs">
      {failed_count > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-danger" />
          <span className="text-text-muted">
            {failed_count} failed route{failed_count !== 1 ? 's' : ''}
          </span>
        </div>
      )}
      {pending_entity_count > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-warning" />
          <span className="text-text-muted">
            {pending_entity_count} pending hold{pending_entity_count !== 1 ? 's' : ''}
          </span>
        </div>
      )}
      {sent_count > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-success" />
          <span className="text-text-muted">
            {sent_count} sent
          </span>
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────

export default function Today() {
  const [mode, setMode] = useState(getTimeMode);
  const [data, setData] = useState(null);
  const [routing, setRouting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Track manual override so server mode does not fight user toggle
  const modeOverridden = useRef(false);

  // Auto-update mode every minute (only if not manually overridden)
  useEffect(() => {
    const timer = setInterval(() => {
      if (!modeOverridden.current) {
        setMode(getTimeMode());
      }
    }, 60000);
    return () => clearInterval(timer);
  }, []);

  // Fetch data
  useEffect(() => {
    setLoading(true);
    setError(null);

    Promise.all([
      api.todayBrief(),
      api.routingStatus().catch(() => null),
    ])
      .then(([result, routingResult]) => {
        setData(result);
        setRouting(routingResult);
        // Sync mode from server if available, but allow manual override
        if (result.mode && !modeOverridden.current) {
          setMode(result.mode);
        }
      })
      .catch((err) => {
        console.error('Failed to load today brief:', err);
        setError(err.message || 'Failed to load data');
      })
      .finally(() => setLoading(false));
  }, []);

  const handleToggleMode = () => {
    modeOverridden.current = true;
    setMode((m) => (m === 'morning' ? 'evening' : 'morning'));
  };

  // ── Loading state ──

  if (loading) {
    return (
      <div className="py-12 text-center text-text-dim">Loading...</div>
    );
  }

  // ── Error state ──

  if (error && !data) {
    return (
      <div className="py-6 space-y-4">
        <h1 className="text-2xl font-bold text-text">
          {getTimeMode() === 'morning' ? 'Good morning' : 'Evening recap'}
        </h1>
        <p className="text-sm text-text-dim">{formatDate()}</p>
        <div className="bg-card border border-danger/30 rounded-lg p-5">
          <p className="text-sm text-danger">Could not load today's brief.</p>
          <p className="text-xs text-text-dim mt-1">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-3 text-xs text-accent hover:text-accent-hover cursor-pointer bg-transparent border-0 p-0"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  // ── Normalize data with safe defaults ──

  const d = data || {};
  const conversations = d.conversations_today || [];
  const reviewCount = d.needs_review_count || 0;
  const pendingCount = d.pending_count || 0;
  const processingCount = d.processing_count || 0;
  const recentBeliefs = d.recent_beliefs || [];
  const contested = d.contested_beliefs || [];
  const myCommitments = d.my_commitments || [];
  const theirCommitments = d.their_commitments || [];
  const unresolvedSpeakers = d.unresolved_speakers || [];
  const recentConversations = d.recent_conversations || [];

  // ── Detect truly empty state ──

  const hasAnyData =
    conversations.length > 0 ||
    reviewCount > 0 ||
    recentBeliefs.length > 0 ||
    contested.length > 0 ||
    myCommitments.length > 0 ||
    theirCommitments.length > 0 ||
    unresolvedSpeakers.length > 0;

  // ── Render ──

  return (
    <div className="py-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text">
            {mode === 'morning' ? 'Good morning' : 'Evening recap'}
          </h1>
          <p className="text-sm text-text-dim mt-1">{formatDate()}</p>
        </div>
        <button
          onClick={handleToggleMode}
          className="text-xs text-text-dim border border-border rounded px-2.5 py-1
                     hover:border-border-light hover:text-text-muted transition-colors
                     cursor-pointer bg-transparent"
        >
          {mode === 'morning' ? 'Evening' : 'Morning'} view
        </button>
      </div>

      {/* Pipeline status bar */}
      <PipelineStatusBar pending={pendingCount} processing={processingCount} />
      <RoutingStatusBar routing={routing} />

      {/* Empty data notice */}
      {!hasAnyData && (
        <div className="bg-card border border-border rounded-lg p-6 text-center">
          <p className="text-sm text-text-muted">
            No major changes overnight. No urgent review items.
          </p>
          <p className="text-xs text-text-dim mt-2">
            Drop audio files into the inbox or check the{' '}
            <Link to="/pipeline" className="text-accent hover:text-accent-hover">
              Pipeline
            </Link>{' '}
            page to get started.
          </p>
        </div>
      )}

      {/* ─── Morning Mode ─── */}
      {mode === 'morning' && hasAnyData && (
        <div className="grid gap-4 md:grid-cols-2">
          {/* Row 1 */}
          <NeedsReviewCard count={reviewCount} />
          <WhatChangedCard beliefs={recentBeliefs} />

          {/* Row 2 */}
          <CommitmentsCard mine={myCommitments} theirs={theirCommitments} />
          <TodayConversationsCard conversations={conversations} />

          {/* Row 3 — conditional */}
          {unresolvedSpeakers.length > 0 && (
            <UnresolvedSpeakersCard speakers={unresolvedSpeakers} />
          )}
        </div>
      )}

      {/* ─── Evening Mode ─── */}
      {mode === 'evening' && hasAnyData && (
        <div className="grid gap-4 md:grid-cols-2">
          {/* Row 1 */}
          <WhatHappenedCard conversations={conversations} />
          <WhatChangedCard beliefs={recentBeliefs} />

          {/* Row 2 */}
          <StillNeedsActionCard reviewCount={reviewCount} speakers={unresolvedSpeakers} />
          <CommitmentsCard mine={myCommitments} theirs={theirCommitments} />

          {/* Row 3 — conditional */}
          {contested.length > 0 && (
            <ContestedBeliefsCard beliefs={contested} />
          )}
        </div>
      )}
    </div>
  );
}
