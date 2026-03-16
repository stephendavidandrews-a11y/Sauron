import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info?.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: 48, textAlign: 'center', maxWidth: 500,
          margin: '80px auto', color: '#e5e7eb',
        }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>&#x26A0;</div>
          <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>
            Something went wrong
          </h1>
          <p style={{ fontSize: 13, color: '#9ca3af', marginBottom: 24 }}>
            {this.state.error?.message || 'An unexpected error occurred.'}
          </p>
          <button
            onClick={() => { this.setState({ hasError: false, error: null }); }}
            style={{
              padding: '10px 24px', fontSize: 14, fontWeight: 500,
              background: '#3b82f6', color: '#fff', border: 'none',
              borderRadius: 6, cursor: 'pointer', marginRight: 12,
            }}
          >
            Try Again
          </button>
          <button
            onClick={() => { window.location.href = '/'; }}
            style={{
              padding: '10px 24px', fontSize: 14, fontWeight: 500,
              background: 'transparent', color: '#9ca3af',
              border: '1px solid #1f2937', borderRadius: 6, cursor: 'pointer',
            }}
          >
            Go Home
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
