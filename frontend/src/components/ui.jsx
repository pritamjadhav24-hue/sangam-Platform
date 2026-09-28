// SANGAM shared UI kit: the same building blocks on every citizen and admin
// page, so both feel like one platform. Styling lives in design-system.css.
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  CircleAlert, CircleCheck, CircleX, Info, Inbox, LoaderCircle, TriangleAlert, X,
} from 'lucide-react';

// ---- Toasts -----------------------------------------------------------------

const ToastContext = createContext(() => {});
const TONE_ICON = { success: CircleCheck, error: CircleX, warning: TriangleAlert, info: Info };

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(1);
  const dismiss = useCallback(id => setToasts(items => items.filter(item => item.id !== id)), []);
  const toast = useCallback(({ tone = 'info', title, message, timeout = 5000 }) => {
    const id = nextId.current++;
    setToasts(items => [...items.slice(-3), { id, tone, title, message }]);
    if (timeout) setTimeout(() => dismiss(id), timeout);
    return id;
  }, [dismiss]);
  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-region" role="status" aria-live="polite">
        {toasts.map(item => {
          const Icon = TONE_ICON[item.tone] || Info;
          return (
            <div key={item.id} className={`toast toast-${item.tone}`}>
              <Icon size={18} aria-hidden="true" />
              <div className="toast-body">
                {item.title && <b>{item.title}</b>}
                {item.message && <span>{item.message}</span>}
              </div>
              <button type="button" className="toast-close" onClick={() => dismiss(item.id)} aria-label="Dismiss notification"><X size={16} aria-hidden="true" /></button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

/** toast({ tone: 'success' | 'error' | 'warning' | 'info', title, message }) */
export function useToast() {
  return useContext(ToastContext);
}

// ---- Empty / error / loading states -------------------------------------------

export function EmptyState({ icon: Icon = Inbox, title, message, action }) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon" aria-hidden="true"><Icon size={28} /></span>
      <b>{title}</b>
      {message && <p>{message}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ title = 'Something went wrong', message, onRetry, retryLabel = 'Try again' }) {
  return (
    <div className="error-state" role="alert">
      <CircleAlert size={20} aria-hidden="true" />
      <div><b>{title}</b>{message && <p>{message}</p>}</div>
      {onRetry && <button type="button" className="outline small" onClick={onRetry}>{retryLabel}</button>}
    </div>
  );
}

export function Skeleton({ lines = 3, label = 'Loading' }) {
  return (
    <div className="skeleton-block" role="status" aria-label={label}>
      {Array.from({ length: lines }, (_, index) => <span key={index} className="skeleton-line" style={{ width: `${100 - (index % 3) * 18}%` }} />)}
    </div>
  );
}

export function SkeletonCards({ count = 3, label = 'Loading' }) {
  return (
    <div className="skeleton-cards" role="status" aria-label={label}>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="card skeleton-card"><span className="skeleton-line" /><span className="skeleton-line" /><span className="skeleton-line short" /></div>
      ))}
    </div>
  );
}

export function Spinner({ label }) {
  return <span className="inline-spinner" role="status"><LoaderCircle className="spin" size={16} aria-hidden="true" />{label}</span>;
}

// ---- Status pill (health / incidents / roles) ----------------------------------

const PILL_TONE = {
  AVAILABLE: 'ok', HEALTHY: 'ok', RESOLVED: 'ok', VERIFIED: 'ok', AUTHORITATIVE: 'ok', AUTO_FILLED: 'ok',
  DEGRADED: 'warn', AUTHORIZED_FALLBACK: 'warn', AUTO_FILLED_VIA_FALLBACK: 'warn', NO_RECORD: 'warn', WARNING: 'warn',
  UNAVAILABLE: 'bad', OPEN: 'bad', MISCONFIGURED: 'bad', NOT_AUTHORIZED: 'muted', PENDING: 'bad', NOT_ATTACHED: 'bad', CRITICAL: 'bad',
  UNKNOWN: 'muted', NOT_CONFIGURED: 'muted', INFO: 'info', SUCCESS: 'ok',
};

export function StatusPill({ status, label, title }) {
  const tone = PILL_TONE[String(status || 'UNKNOWN').toUpperCase()] || 'muted';
  const text = label || String(status || 'Unknown').replace(/_/g, ' ').toLowerCase().replace(/^\w/, char => char.toUpperCase());
  return <span className={`status-pill tone-${tone}`} title={title}><span className="status-dot" aria-hidden="true" />{text}</span>;
}

// ---- Tooltip -------------------------------------------------------------------

export function Tooltip({ text, children }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className="tooltip-anchor" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}>
      <span aria-describedby={id}>{children}</span>
      <span role="tooltip" id={id} className={`tooltip${open ? ' open' : ''}`}>{text}</span>
    </span>
  );
}

// ---- Activity timeline (interoperability trace) ----------------------------------

const STEP_TONE = { ok: 'ok', warn: 'warn', fail: 'bad', info: 'info' };

function timeOf(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function ActivityTimeline({ steps = [] }) {
  const ordered = useMemo(() => steps, [steps]);
  return (
    <ol className="activity-timeline">
      {ordered.map((step, index) => (
        <li key={`${step.stage}-${index}`} className={`activity-step tone-${STEP_TONE[step.status] || 'info'}`}>
          <time dateTime={step.at}>{timeOf(step.at)}</time>
          <span className="activity-marker" aria-hidden="true" />
          <div className="activity-content">
            <b>{step.title}</b>
            {(step.actor || step.target) && (
              <span className="activity-route">{step.actor || 'SANGAM'}{step.target ? ` → ${step.target}` : ''}</span>
            )}
            {step.method && <span className="activity-meta">Found by {step.method}{typeof step.confidence === 'number' ? ` · confidence ${step.confidence}` : ''}</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}

// Keeps a value's previous render (used to announce changes, e.g. recovery).
export function usePrevious(value) {
  const ref = useRef();
  useEffect(() => { ref.current = value; }, [value]);
  return ref.current;
}
