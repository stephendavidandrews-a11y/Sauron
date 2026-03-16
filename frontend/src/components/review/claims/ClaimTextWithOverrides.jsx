import { C } from '../styles';

export function ClaimTextWithOverrides({ text, overrides }) {
  if (!overrides || !Array.isArray(overrides) || overrides.length === 0) {
    return <span>{text}</span>;
  }

  // Sort overrides by start position
  const sorted = [...overrides].sort((a, b) => a.start - b.start);
  const parts = [];
  let lastEnd = 0;

  for (const ov of sorted) {
    // Text before this override
    if (ov.start > lastEnd) {
      parts.push(<span key={`t${lastEnd}`}>{text.slice(lastEnd, ov.start)}</span>);
    }
    // The overridden span with amber highlight
    parts.push(
      <span key={`o${ov.start}`} title={`Resolved: ${ov.resolved_name}`}
        style={{ background: `${C.amber}33`, color: C.amber, borderRadius: 2, padding: '0 2px' }}>
        {text.slice(ov.start, ov.end)}
        <span style={{ fontSize: 10, fontWeight: 600, marginLeft: 2 }}>{ov.resolved_name.split(' ').slice(1).join(' ')}</span>
      </span>
    );
    lastEnd = ov.end;
  }

  // Remaining text after last override
  if (lastEnd < text.length) {
    parts.push(<span key={`t${lastEnd}`}>{text.slice(lastEnd)}</span>);
  }

  return <span>{parts}</span>;
}

