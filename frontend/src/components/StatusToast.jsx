import { useState, useEffect, useCallback, createContext, useContext } from 'react';
import { C } from '../utils/colors';

const ToastContext = createContext(null);

const COLORS = {
  success: { bg: 'rgba(34,197,94,0.15)', border: 'rgba(34,197,94,0.3)', text: '#4ade80' },
  error:   { bg: 'rgba(239,68,68,0.15)', border: 'rgba(239,68,68,0.3)', text: '#f87171' },
  warning: { bg: 'rgba(234,179,8,0.15)', border: 'rgba(234,179,8,0.3)', text: '#facc15' },
  info:    { bg: 'rgba(59,130,246,0.15)', border: 'rgba(59,130,246,0.3)', text: '#60a5fa' },
};

let toastId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, { type = 'info', duration = 5000, action = null } = {}) => {
    const id = ++toastId;
    setToasts(prev => [...prev, { id, message, type, action }]);
    if (duration > 0) {
      setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), duration);
    }
    return id;
  }, []);

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const toast = {
    success: (msg, opts) => addToast(msg, { type: 'success', duration: 3000, ...opts }),
    error: (msg, opts) => addToast(msg, { type: 'error', duration: 8000, ...opts }),
    warning: (msg, opts) => addToast(msg, { type: 'warning', duration: 5000, ...opts }),
    info: (msg, opts) => addToast(msg, { type: 'info', ...opts }),
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div style={{
        position: 'fixed', bottom: 16, right: 16, zIndex: 9999,
        display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 400,
      }}>
        {toasts.map(t => {
          const c = COLORS[t.type] || COLORS.info;
          return (
            <div key={t.id} style={{
              background: c.bg, border: `1px solid ${c.border}`, borderRadius: 8,
              padding: '10px 14px', color: c.text, fontSize: 13,
              display: 'flex', alignItems: 'center', gap: 8,
              animation: 'fadeIn 0.2s ease-out',
            }}>
              <span style={{ flex: 1 }}>{t.message}</span>
              {t.action && (
                <button onClick={t.action.onClick} style={{
                  background: 'none', border: `1px solid ${c.border}`, borderRadius: 4,
                  color: c.text, fontSize: 11, padding: '2px 8px', cursor: 'pointer',
                }}>{t.action.label}</button>
              )}
              <button onClick={() => removeToast(t.id)} style={{
                background: 'none', border: 'none', color: c.text, cursor: 'pointer',
                fontSize: 14, padding: 0, opacity: 0.6,
              }}>\u00d7</button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
