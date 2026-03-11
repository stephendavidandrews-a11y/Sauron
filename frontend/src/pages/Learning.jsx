import { useState, useEffect } from 'react';
import { api } from '../api';

export default function Learning() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [editingAmendment, setEditingAmendment] = useState(null);
  const [editText, setEditText] = useState('');

  const load = () => {
    api.learningDashboard()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const result = await api.triggerLearningAnalysis();
      if (result.status === 'generated') {
        load();
      } else {
        alert(result.message || 'No changes needed');
      }
    } catch (e) {
      alert('Analysis failed: ' + e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleToggleAmendment = async (id, active) => {
    try {
      await api.toggleAmendment(id, active);
      load();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  };

  const handleSaveAmendment = async (id) => {
    try {
      await api.editAmendment(id, editText);
      setEditingAmendment(null);
      load();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  };

  if (loading) {
    return <div className="py-12 text-center text-text-dim">Loading...</div>;
  }

  if (!data) {
    return (
      <div className="py-12 text-center text-text-dim">
        Failed to load learning data.
      </div>
    );
  }

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-text">Learning</h1>
        <button
          onClick={handleAnalyze}
          disabled={analyzing || data.pending_corrections < 5}
          className="px-4 py-2 rounded-md text-sm font-medium transition-colors cursor-pointer
                     bg-accent text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {analyzing ? 'Analyzing...' : 'Run Analysis'}
        </button>
      </div>

      {/* Stats */}
      <div className="flex gap-4 flex-wrap">
        <StatCard label="Total Corrections" value={data.total_corrections} />
        <StatCard label="Pending" value={data.pending_corrections} accent />
        <StatCard label="Amendments" value={data.amendments?.length || 0} />
        <StatCard label="Contact Profiles" value={data.contact_preferences?.length || 0} />
      </div>

      {/* Active Amendment */}
      {data.active_amendment && (
        <div className="bg-card border border-border rounded-lg p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide">
              Active Amendment ({data.active_amendment.version})
            </h3>
            <button
              onClick={() => {
                setEditingAmendment(data.active_amendment.id);
                setEditText(data.active_amendment.amendment_text);
              }}
              className="px-3 py-1 text-xs rounded bg-card-hover text-text-muted hover:text-text
                         border border-border cursor-pointer"
            >
              Edit
            </button>
          </div>

          {editingAmendment === data.active_amendment.id ? (
            <div>
              <textarea
                value={editText}
                onChange={e => setEditText(e.target.value)}
                className="w-full h-64 bg-bg border border-border rounded p-3 text-sm text-text
                           font-mono resize-y focus:outline-none focus:border-accent"
              />
              <div className="flex gap-2 mt-2 justify-end">
                <button
                  onClick={() => setEditingAmendment(null)}
                  className="px-3 py-1.5 text-xs rounded bg-card-hover text-text-muted
                             border border-border cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleSaveAmendment(data.active_amendment.id)}
                  className="px-3 py-1.5 text-xs rounded bg-accent text-white cursor-pointer"
                >
                  Save
                </button>
              </div>
            </div>
          ) : (
            <pre className="text-sm text-text-muted whitespace-pre-wrap leading-relaxed font-mono
                            bg-bg rounded p-4 max-h-96 overflow-auto">
              {data.active_amendment.amendment_text}
            </pre>
          )}

          <div className="mt-3 text-xs text-text-dim">
            Generated from {data.active_amendment.correction_count || '?'} corrections
            {' \u00B7 '}
            {data.active_amendment.created_at?.slice(0, 10)}
          </div>
        </div>
      )}

      {!data.active_amendment && data.total_corrections > 0 && (
        <div className="bg-card border border-border rounded-lg p-5 text-center">
          <p className="text-text-muted text-sm mb-2">No active amendment yet.</p>
          <p className="text-text-dim text-xs">
            {data.pending_corrections >= 5
              ? 'You have enough corrections \u2014 click "Run Analysis" to generate one.'
              : `Need ${5 - data.pending_corrections} more corrections of the same type before analysis can run.`}
          </p>
        </div>
      )}

      {data.total_corrections === 0 && (
        <div className="bg-card border border-border rounded-lg p-5 text-center">
          <p className="text-text-muted text-sm mb-2">No corrections yet.</p>
          <p className="text-text-dim text-xs">
            Review conversations and correct claims, speakers, or extractions.
            After 5+ corrections of the same type, the system will learn from them.
          </p>
        </div>
      )}

      {/* Corrections by type */}
      {Object.keys(data.corrections_by_type || {}).length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-3">
            Corrections by Type
          </h3>
          <div className="space-y-2">
            {Object.entries(data.corrections_by_type).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between text-sm">
                <span className="text-text">{type}</span>
                <div className="flex items-center gap-2">
                  <div className="h-2 rounded-full bg-accent/20 w-24">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${Math.min(100, (count / 5) * 100)}%` }}
                    />
                  </div>
                  <span className="text-text-dim w-8 text-right">{count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Amendment History */}
      {data.amendments?.length > 1 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-3">
            Amendment History
          </h3>
          <div className="space-y-2">
            {data.amendments.map(a => (
              <div key={a.id} className="flex items-center justify-between p-3 rounded-md hover:bg-card-hover text-sm">
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-mono ${a.active ? 'text-success' : 'text-text-dim'}`}>
                    {a.version}
                  </span>
                  <span className="text-text-muted">
                    {a.correction_count} corrections
                  </span>
                  <span className="text-text-dim text-xs">{a.created_at?.slice(0, 10)}</span>
                </div>
                <button
                  onClick={() => handleToggleAmendment(a.id, !a.active)}
                  className={`px-2 py-1 text-xs rounded cursor-pointer border ${
                    a.active
                      ? 'bg-success/10 text-success border-success/30'
                      : 'bg-card-hover text-text-dim border-border'
                  }`}
                >
                  {a.active ? 'Active' : 'Activate'}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Corrections */}
      {data.recent_corrections?.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-3">
            Recent Corrections
          </h3>
          <div className="space-y-1">
            {data.recent_corrections.slice(0, 10).map(c => (
              <div key={c.id} className="flex items-center gap-3 p-2 text-sm rounded hover:bg-card-hover">
                <span className="px-2 py-0.5 text-xs rounded bg-purple/15 text-purple font-medium">
                  {c.error_type}
                </span>
                <span className="text-text-muted flex-1 truncate">
                  {c.new_value?.slice(0, 80)}
                </span>
                <span className="text-text-dim text-xs shrink-0">
                  {c.created_at?.slice(0, 10)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Contact Preferences */}
      {data.contact_preferences?.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-3">
            Contact Preferences
          </h3>
          <div className="space-y-2">
            {data.contact_preferences.map(cp => (
              <div key={cp.id} className="p-3 rounded-md bg-bg text-sm">
                <div className="font-medium text-text mb-1">
                  {cp.canonical_name || cp.contact_id}
                </div>
                <div className="flex gap-4 flex-wrap text-xs text-text-dim">
                  {cp.commitment_confidence_threshold != null && (
                    <span>Confidence threshold: {cp.commitment_confidence_threshold}</span>
                  )}
                  {cp.extraction_depth && <span>Depth: {cp.extraction_depth}</span>}
                  {cp.vocal_alert_sensitivity && <span>Vocal sensitivity: {cp.vocal_alert_sensitivity}</span>}
                  {cp.relationship_importance != null && (
                    <span>Importance: {cp.relationship_importance}</span>
                  )}
                </div>
                {cp.custom_notes && (
                  <div className="text-xs text-text-muted mt-1 italic">{cp.custom_notes}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, accent }) {
  return (
    <div className="bg-card border border-border rounded-lg px-5 py-4 min-w-[140px]">
      <div className="text-xs text-text-dim uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-2xl font-bold ${accent ? 'text-accent' : 'text-text'}`}>
        {value}
      </div>
    </div>
  );
}
