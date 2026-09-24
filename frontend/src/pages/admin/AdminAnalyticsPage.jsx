import { useEffect, useState } from 'react';

const OUTCOME_LABELS = {
  automaticallyVerified: 'Auto-verified',
  manuallyFulfilled: 'Manually fulfilled',
  citizenActionRequired: 'Citizen action required',
  officerReviewRequired: 'Officer review required',
  retryInProgress: 'Retrying',
  processing: 'Processing',
};

const REQUIREMENT_LABELS = {
  fulfilledAutomatically: 'Fulfilled automatically',
  fulfilledManually: 'Fulfilled manually',
  pending: 'Pending',
  actionRequired: 'Action required',
  retrying: 'Retrying',
  failed: 'Failed / rejected',
};

const TREND_LABELS = {
  applications: 'Application activity',
  fulfillment: 'Fulfilled requirements (by application last update)',
  providerFailures: 'Provider job failures',
  incidents: 'Provider incidents',
  recovery: 'Recovery / replay activity',
};

const EMPTY_FILTERS = { start: '', end: '', status: '', outcome: '', provider: '', requirement: '', incidentStatus: '' };

function Metric({ label, value, onClick, tone }) {
  const content = (
    <>
      <small className="muted" style={{ display: 'block' }}>{label}</small>
      <b style={{ fontSize: '22px', color: tone === 'warn' && value > 0 ? '#a25a12' : '#562C2C' }}>{value}</b>
    </>
  );
  return onClick ? (
    <button type="button" className="analytics-metric" onClick={onClick}>{content}</button>
  ) : (
    <div className="analytics-metric">{content}</div>
  );
}

function Trend({ label, trend }) {
  const max = Math.max(1, ...trend.series.map(point => point.count));
  return (
    <div style={{ border: '1px solid #E8D5D0', borderRadius: '6px', padding: '12px' }}>
      <b style={{ fontSize: '13px', color: '#562C2C' }}>{label}</b>
      {trend.limited ? (
        <p className="muted" style={{ margin: '8px 0 0', fontSize: '13px' }}>
          Limited demo data available for this trend
          {trend.series.length === 1 && ` (activity on a single day: ${trend.series[0].date}, ${trend.series[0].count})`}.
        </p>
      ) : (
        <div style={{ display: 'grid', gap: '4px', marginTop: '8px' }}>
          {trend.series.map(point => (
            <div key={point.date} style={{ display: 'grid', gridTemplateColumns: '90px 1fr 32px', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
              <span className="muted">{point.date}</span>
              <span style={{ height: '8px', borderRadius: '4px', background: '#127475', width: `${(point.count / max) * 100}%` }} />
              <b>{point.count}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AdminAnalyticsPage({ api, onNavigate, onOpenProvider, onOpenApplication }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [report, setReport] = useState(null);
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.adminProviderRegistry().then(res => setProviders(res.providers || [])).catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    api.adminAnalytics(applied)
      .then(res => { if (active) setReport(res); })
      .catch(err => { if (active) setError(err.message || 'Failed to load analytics.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [applied]);

  const update = key => event => setFilters(current => ({ ...current, [key]: event.target.value }));
  const requirementCodes = report?.requirements?.byRequirement?.map(item => item.requirementCode) || [];
  const providerName = id => report?.providerNames?.[id] || id;

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">Operational Intelligence · Admin</p>
          <h1>Analytics &amp; Reports</h1>
          <p>Read-only figures computed live from SANGAM's persisted applications, requirements, provider jobs, incidents and audit ledger.</p>
        </div>
      </div>

      <form
        className="card"
        style={{ marginBottom: '20px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px', alignItems: 'end' }}
        onSubmit={event => { event.preventDefault(); setApplied(filters); }}
      >
        <label className="analytics-filter">From<input type="date" value={filters.start} onChange={update('start')} /></label>
        <label className="analytics-filter">To<input type="date" value={filters.end} onChange={update('end')} /></label>
        <label className="analytics-filter">Application status
          <select value={filters.status} onChange={update('status')}>
            <option value="">All</option>
            {['DRAFT', 'IN_PROGRESS', 'SUBMITTED', 'WAITING_FOR_OFFICER', 'CONFLICT_DETECTED', 'VERIFICATION_FAILED', 'APPROVED', 'REJECTED'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="analytics-filter">Outcome
          <select value={filters.outcome} onChange={update('outcome')}>
            <option value="">All</option>
            {Object.entries(OUTCOME_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <label className="analytics-filter">Provider
          <select value={filters.provider} onChange={update('provider')}>
            <option value="">All</option>
            {providers.map(p => <option key={p.providerId} value={p.providerId}>{p.name}</option>)}
          </select>
        </label>
        <label className="analytics-filter">Requirement
          <input value={filters.requirement} onChange={update('requirement')} placeholder="e.g. INCOME_PROOF" list="analytics-requirements" />
          <datalist id="analytics-requirements">{requirementCodes.map(code => <option key={code} value={code} />)}</datalist>
        </label>
        <label className="analytics-filter">Incident state
          <select value={filters.incidentStatus} onChange={update('incidentStatus')}>
            <option value="">All</option>
            <option value="OPEN">Open</option>
            <option value="RESOLVED">Resolved</option>
          </select>
        </label>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button type="submit" className="primary" disabled={loading}>{loading ? 'Loading…' : 'Apply'}</button>
          <button type="button" className="outline" onClick={() => { setFilters(EMPTY_FILTERS); setApplied(EMPTY_FILTERS); }}>Reset</button>
        </div>
      </form>

      {error && <div className="alert danger" role="alert">{error}</div>}
      {loading && !report && <p className="loading-state">Computing analytics…</p>}

      {report && (
        <>
          <div className="card" style={{ marginBottom: '20px' }}>
            <div className="section-heading">
              <div>
                <h2>Application overview</h2>
                <p>Outcome buckets are mutually exclusive and derived from requirement-level state.</p>
              </div>
              <span className="count-badge">Total: {report.applications.total}</span>
            </div>
            <div className="analytics-grid">
              <Metric label="Total applications" value={report.applications.total} onClick={() => onNavigate('adminApplications')} />
              <Metric label="Submitted" value={report.applications.submitted} onClick={() => onNavigate('adminApplications')} />
              {Object.entries(OUTCOME_LABELS).map(([key, label]) => (
                <Metric key={key} label={label} value={report.applications[key]} tone={key === 'citizenActionRequired' || key === 'officerReviewRequired' ? 'warn' : undefined} />
              ))}
            </div>
            {report.applications.appIds.length > 0 && (
              <div style={{ marginTop: '12px', display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                <small className="muted">Matching applications:</small>
                {report.applications.appIds.slice(0, 12).map(id => (
                  <button key={id} type="button" className="small outline" onClick={() => onOpenApplication(id)}>{id}</button>
                ))}
                {report.applications.appIds.length > 12 && <small className="muted">+{report.applications.appIds.length - 12} more</small>}
              </div>
            )}
          </div>

          <div className="card" style={{ marginBottom: '20px' }}>
            <div className="section-heading">
              <h2>Requirement fulfillment</h2>
              <span className="count-badge">Requirements: {report.requirements.total}</span>
            </div>
            <div className="analytics-grid">
              {Object.entries(REQUIREMENT_LABELS).map(([key, label]) => (
                <Metric key={key} label={label} value={report.requirements[key]} tone={key === 'actionRequired' || key === 'failed' ? 'warn' : undefined} />
              ))}
              <Metric label="Fulfilled via fallback provider" value={report.requirements.fallbackUsed} />
            </div>
            {report.requirements.byRequirement.length > 0 && (
              <div style={{ overflowX: 'auto', marginTop: '14px' }}>
                <table>
                  <thead><tr><th>Requirement</th><th>Total</th><th>Auto</th><th>Manual</th><th>Pending</th><th>Action req.</th><th>Retrying</th><th>Failed</th><th>Fallback</th></tr></thead>
                  <tbody>
                    {report.requirements.byRequirement.map(row => (
                      <tr key={row.requirementCode}>
                        <td><code>{row.requirementCode}</code></td>
                        <td>{row.total || 0}</td>
                        <td>{row.fulfilledAutomatically || 0}</td>
                        <td>{row.fulfilledManually || 0}</td>
                        <td>{row.pending || 0}</td>
                        <td>{row.actionRequired || 0}</td>
                        <td>{row.retrying || 0}</td>
                        <td>{row.failed || 0}</td>
                        <td>{row.fallbackUsed || 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card" style={{ marginBottom: '20px' }}>
            <div className="section-heading">
              <div>
                <h2>Provider &amp; integration operations</h2>
                <p>Health is current; job, incident and replay figures respect the date/provider filters.</p>
              </div>
            </div>
            <div className="analytics-grid">
              <Metric label="Registered providers" value={report.providers.registered} onClick={() => onNavigate('adminProviders')} />
              <Metric label="Healthy" value={report.providers.healthy} />
              <Metric label="Degraded" value={report.providers.degraded} tone="warn" />
              <Metric label="Down" value={report.providers.down} tone="warn" />
              <Metric label="Provider jobs" value={report.providers.jobs.total} />
              <Metric label="Retries executed" value={report.providers.jobs.retries} />
              <Metric label="Dead-letter jobs" value={report.providers.jobs.deadLetter} tone="warn" onClick={() => onNavigate('adminAlerts')} />
              <Metric label="Incidents (open)" value={report.providers.incidents.open} tone="warn" onClick={() => onNavigate('adminAlerts')} />
              <Metric label="Incidents (resolved)" value={report.providers.incidents.resolved} onClick={() => onNavigate('adminAlerts')} />
              <Metric label="Fallback fulfillments" value={report.providers.fallbackUsed} />
              <Metric label="Automatic recovery replays" value={report.providers.replays.automaticRecovery} onClick={() => onNavigate('audit')} />
              <Metric label="Manual replays" value={report.providers.replays.manual} onClick={() => onNavigate('audit')} />
            </div>
            {Object.keys(report.providers.incidents.byProvider).length > 0 && (
              <div style={{ marginTop: '12px', display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                <small className="muted">Incidents by provider:</small>
                {Object.entries(report.providers.incidents.byProvider).map(([system, count]) => {
                  const registered = providers.find(p => p.name === system);
                  return registered ? (
                    <button key={system} type="button" className="small outline" onClick={() => onOpenProvider(registered.providerId)}>{system}: {count}</button>
                  ) : (
                    <span key={system} className="tag" style={{ fontSize: '11px' }} title="Not a currently registered provider">{providerName(system)}: {count}</span>
                  );
                })}
              </div>
            )}
          </div>

          <div className="card">
            <div className="section-heading">
              <div>
                <h2>Trends</h2>
                <p>Daily counts from persisted timestamps. Sparse history is labelled rather than extrapolated.</p>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px' }}>
              {Object.entries(TREND_LABELS).map(([key, label]) => <Trend key={key} label={label} trend={report.trends[key]} />)}
            </div>
          </div>
        </>
      )}
    </main>
  );
}
