import { useState, useEffect, useRef } from 'react';

const COMMANDS = [
  { pattern: /^today$/i, action: '/', label: 'Go to Today' },
  { pattern: /^prep\s+(.+)/i, action: (m) => `/prep/${encodeURIComponent(m[1])}`, label: 'Open person/topic brief' },
  { pattern: /^review\s+today$/i, action: '/review', label: 'Review today\'s conversations' },
  { pattern: /^review$/i, action: '/review', label: 'Open Review' },
  { pattern: /^search\s+(.+)/i, action: (m) => `/search?q=${encodeURIComponent(m[1])}`, label: 'Search' },
  { pattern: /^call\s+(.+)/i, action: (m) => `/prep/${encodeURIComponent(m[1])}`, label: 'Surprise call card' },
  { pattern: /^topic\s+(.+)/i, action: (m) => `/prep/${encodeURIComponent(m[1])}`, label: 'Topic brief' },
];

const SUGGESTIONS = [
  { text: 'prep heath', desc: 'Open person brief' },
  { text: 'prep tomorrow', desc: 'Tomorrow\'s meetings' },
  { text: 'review today', desc: 'Review processed conversations' },
  { text: 'search tokenized collateral', desc: 'Semantic search' },
  { text: 'today', desc: 'Go to Today' },
];

export default function CommandPalette({ open, onClose, onNavigate }) {
  const [query, setQuery] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;

    for (const cmd of COMMANDS) {
      const match = q.match(cmd.pattern);
      if (match) {
        const path = typeof cmd.action === 'function' ? cmd.action(match) : cmd.action;
        onNavigate(path);
        return;
      }
    }

    // Default: treat as search
    onNavigate(`/search?q=${encodeURIComponent(q)}`);
  };

  const handleSuggestionClick = (text) => {
    setQuery(text);
    // Auto-execute
    for (const cmd of COMMANDS) {
      const match = text.match(cmd.pattern);
      if (match) {
        const path = typeof cmd.action === 'function' ? cmd.action(match) : cmd.action;
        onNavigate(path);
        return;
      }
    }
  };

  if (!open) return null;

  const filtered = query
    ? SUGGESTIONS.filter(s => s.text.toLowerCase().includes(query.toLowerCase()))
    : SUGGESTIONS;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-[20vh] bg-black/60"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-card border border-border rounded-xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <form onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command..."
            className="w-full px-5 py-4 bg-transparent text-text text-base border-b border-border
                       outline-none placeholder:text-text-dim"
          />
        </form>

        <div className="max-h-64 overflow-y-auto py-2">
          {filtered.map((s, i) => (
            <button
              key={i}
              onClick={() => handleSuggestionClick(s.text)}
              className="w-full text-left px-5 py-2.5 flex items-center justify-between
                         hover:bg-card-hover transition-colors cursor-pointer bg-transparent border-0"
            >
              <span className="text-sm text-text font-mono">{s.text}</span>
              <span className="text-xs text-text-dim">{s.desc}</span>
            </button>
          ))}
          {filtered.length === 0 && query && (
            <div className="px-5 py-3 text-sm text-text-dim">
              Press Enter to search for "{query}"
            </div>
          )}
        </div>

        <div className="px-5 py-2 border-t border-border flex gap-4 text-xs text-text-dim">
          <span><kbd className="font-mono bg-bg px-1 rounded">Enter</kbd> execute</span>
          <span><kbd className="font-mono bg-bg px-1 rounded">Esc</kbd> close</span>
          <span className="ml-auto">T P R S for quick nav</span>
        </div>
      </div>
    </div>
  );
}
