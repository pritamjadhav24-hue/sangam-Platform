import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Building2, Network, RefreshCw, Server } from 'lucide-react';
import { ActivityTimeline, EmptyState, ErrorState, SkeletonCards, StatusPill } from '../../components/ui';

// Interoperability Activity: what SANGAM did behind each Auto-Fill -- the
// requesting department's application, SANGAM's registry and policy
// decisions, the department API that answered, entity resolution,
// normalization and the result. Sanitized by the backend: departments,
// requirements, outcomes and times only (no identities, record contents,
// credentials or database details).

const OUTCOME = {
  AUTO_FILLED: 'Auto-filled',
  AUTO_FILLED_VIA_FALLBACK: 'Auto-filled via authorized fallback',
  PENDING: 'Pending — provider unavailable',
  NO_RECORD: 'No record in connected departments',
  NOT_ATTACHED: 'Not attached — identity not confirmed',
  NOT_COMPLETED: 'Not completed',
};

function when(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'medium' });
}

function Route({ exchange }) {
  return (
    <div className="exchange-route" aria-label="Exchange route">
      <span className="route-node"><Building2 size={15} aria-hidden="true" />{exchange.consumerDepartment || 'Citizen application'}</span>
      <ArrowRight size={16} aria-hidden="true" />
      <span className="route-node hub"><Network size={15} aria-hidden="true" />SANGAM</span>
      <ArrowRight size={16} aria-hidden="true" />
      <span className="route-node"><Server size={15} aria-hidden="true" />{exchange.targetDepartment || 'No department answered'}</span>
    </div>
  );
}

export default function AdminActivityPage({ api, onOpenApplication, applicationId = null }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [openIndex, setOpenIndex] = useState(0);

  const load = useCallback(() => {
    setError('');
    api.adminActivity({ limit: 40, applicationId }).then(setData).catch(err => setError(err.message || 'Activity could not be loaded.'));
  }, [api, applicationId]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 8000);
    return () => clearInterval(interval);
  }, [load]);

  const exchanges = data?.exchanges || [];
  const summary = data?.summary || {};

  return (
    <main className="container admin-page">
      <div className="page-title">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Activity</h1>
          <p>Recent verification requests handled through SANGAM.</p>
        </div>
        <div className="actions">
          <button className="outline button-with-icon" onClick={load}><RefreshCw size={16} aria-hidden="true" />Refresh</button>
        </div>
      </div>

      {error && <ErrorState title="Activity could not be loaded" message={error} onRetry={load} />}

      {data && (
        <div className="activity-summary" aria-label="Exchange summary">
          <div className="card"><span>Auto-filled</span><b>{summary.autoFilled || 0}</b></div>
          <div className="card"><span>Via authorized fallback</span><b>{summary.viaFallback || 0}</b></div>
          <div className="card"><span>Pending (provider unavailable)</span><b>{summary.pending || 0}</b></div>
          <div className="card"><span>No record</span><b>{summary.noRecord || 0}</b></div>
          <div className="card"><span>Not attached</span><b>{summary.notAttached || 0}</b></div>
        </div>
      )}

      {!data && !error && <SkeletonCards count={3} label="Loading activity" />}

      {data && exchanges.length === 0 && (
        <div className="card">
          <EmptyState icon={Network} title="No exchanges yet"
            message="When a citizen uses Auto-Fill, each step SANGAM takes between the departments appears here." />
        </div>
      )}

      <div className="exchange-list">
        {exchanges.map((exchange, index) => {
          const expanded = openIndex === index;
          return (
            <article key={`${exchange.applicationId}-${exchange.requirementCode}-${exchange.completedAt}`} className="card exchange-card">
              <header className="exchange-head">
                <div>
                  <h2>{exchange.requirementLabel}</h2>
                  <p className="muted small-text">
                    <button className="link" onClick={() => onOpenApplication?.(exchange.applicationId)}>{exchange.applicationId}</button>
                    {' · '}{when(exchange.completedAt)}
                  </p>
                </div>
                <StatusPill status={exchange.outcome} label={OUTCOME[exchange.outcome] || exchange.outcome} />
              </header>
              <Route exchange={exchange} />
              <button className="link exchange-toggle" aria-expanded={expanded} onClick={() => setOpenIndex(expanded ? -1 : index)}>
                {expanded ? 'Hide steps' : `Show ${exchange.steps.length} steps`}
              </button>
              {expanded && <ActivityTimeline steps={exchange.steps} />}
            </article>
          );
        })}
      </div>
    </main>
  );
}
