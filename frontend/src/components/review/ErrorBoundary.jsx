import { Component } from 'react';

/**
 * Catches render errors in children and shows a fallback instead of crashing the page.
 * Usage: <ErrorBoundary label="Episodes"><EpisodesTab ... /></ErrorBoundary>
 */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error(`[ErrorBoundary:${this.props.label || 'unknown'}]`, error, info?.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          padding: 16, margin: '8px 0', borderRadius: 8,
          background: '#ef444418', border: '1px solid #ef444444',
          color: '#ef4444', fontSize: 13,
        }}>
          <strong>{this.props.label || 'Section'} failed to render.</strong>
          <div style={{ marginTop: 4, color: '#9ca3af', fontSize: 12 }}>
            {this.state.error?.message || 'Unknown error'}
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              marginTop: 8, padding: '4px 12px', background: '#ef444422',
              border: '1px solid #ef444444', borderRadius: 4, color: '#ef4444',
              cursor: 'pointer', fontSize: 12,
            }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
