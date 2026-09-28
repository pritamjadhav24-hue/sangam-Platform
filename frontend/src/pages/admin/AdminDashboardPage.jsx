import { useEffect, useState } from 'react';

const DEPARTMENT_STATUS = {
  AVAILABLE: ['Available', 'found'], DEGRADED: ['Degraded', 'pending'], UNAVAILABLE: ['Unavailable', 'exception'], NOT_CONFIGURED: ['Not configured', 'pending'],
};

const SYSTEM_STATE_LABEL = {
  OPERATIONAL: 'Healthy',
  DEGRADED_LEDGER_INTEGRITY: 'Degraded — Ledger Integrity',
  DEGRADED_PROVIDER_INCIDENT: 'Degraded — Provider Incident',
};

export default function AdminDashboardPage({ onNavigate, api, onReset }) {
  const [overview, setOverview] = useState(null);
  const [recentJobs, setRecentJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [resetOpen, setResetOpen] = useState(false);

  const loadData = () => {
    setLoading(true);
    setError('');
    Promise.all([
      api.adminOverview(),
      api.adminRecentJobs(8).catch(() => ({ jobs: [] })),
    ])
      .then(([ov, jobsRes]) => {
        setOverview(ov);
        setRecentJobs(jobsRes.jobs || []);
      })
      .catch(err => setError(err.message || 'Failed to load operations overview.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);

  async function handleResetDemo() {
    try {
      await onReset();
      window.location.reload();
    } catch (err) {
      setError(err.message);
      setResetOpen(false);
    }
  }

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Operations Overview</h1>
          <p>System health, applications and exceptions at a glance.</p>
        </div>
        <div className="actions">
          <button className="outline" onClick={loadData} disabled={loading}>
            {loading ? 'Refreshing…' : '↻ Refresh Data'}
          </button>
          <button className="outline danger-text" onClick={() => setResetOpen(true)}>
            Reset Environment
          </button>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}

      {overview && (
        <>
          {/* Top Operational Metrics */}
          <div className="summary-grid">
            <div className={`summary-card ${overview.system.state !== 'OPERATIONAL' ? 'amber' : ''}`}>
              <span className="eyebrow">SANGAM platform</span>
              <b>{SYSTEM_STATE_LABEL[overview.system.state] || overview.system.state}</b>
              <small>
                Audit trail {overview.system.auditChainValid ? 'verified' : 'integrity check failed'}
              </small>
            </div>

            <div className="summary-card blue">
              <span className="eyebrow">Total Applications</span>
              <b>{overview.applications.total}</b>
              <small>
                {overview.applications.automaticallyVerified} Auto-Verified · {overview.applications.manuallyFulfilled} Manually Fulfilled · {overview.applications.retryInProgress} Retrying
              </small>
            </div>

            <div className="summary-card">
              <span className="eyebrow">Department Providers</span>
              <b>{overview.providers.healthy} / {overview.providers.registered}</b>
              <small>
                Registered: {overview.providers.registered} · Healthy: {overview.providers.healthy}
                {overview.providers.down > 0 && ` · Down: ${overview.providers.down}`}
                {overview.providers.degraded > 0 && ` · Degraded: ${overview.providers.degraded}`}
              </small>
            </div>

            <div className={`summary-card ${overview.exceptions.activeProviderIncidents > 0 ? 'amber' : ''}`}>
              <span className="eyebrow">Active Provider Incidents</span>
              <b>{overview.exceptions.activeProviderIncidents}</b>
              <small>System/provider-level outages currently open</small>
            </div>

            <div className={`summary-card ${overview.exceptions.totalAlerts > 0 ? 'amber' : ''}`}>
              <span className="eyebrow">Dead-Letter &amp; Reviews</span>
              <b>{overview.exceptions.totalAlerts}</b>
              <small>
                {overview.exceptions.deadLetterJobs} Dead-letter jobs · {overview.exceptions.entityReviews + overview.exceptions.conflictReviews} Reviews pending
              </small>
            </div>
          </div>

          {(overview.departments || []).some(item => item.headline) && (
            <div className="department-strip" aria-label="Department systems">
              {overview.departments.filter(item => item.headline).map(item => {
                const [label, className] = DEPARTMENT_STATUS[item.status] || DEPARTMENT_STATUS.NOT_CONFIGURED;
                return (
                  <button key={item.key} className="department-pill" onClick={() => onNavigate('adminProviders')}>
                    {item.name.replace(' Department', '')} <span className={`status ${className}`}>{label}</span>
                    {item.activeIncidents > 0 && <small>{item.activeIncidents} incident{item.activeIncidents === 1 ? '' : 's'}</small>}
                  </button>
                );
              })}
            </div>
          )}

          {/* Quick Navigation Cards */}
          <div className="admin-quick-nav grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', marginBottom: '24px' }}>
            <div className="card admin-nav-card" onClick={() => onNavigate('adminApplications')} style={{ cursor: 'pointer' }}>
              <p className="eyebrow">Registry</p>
              <h3>Applications ({overview.applications.total})</h3>
              <p className="muted">Search applications and track verification progress.</p>
              <button className="small outline" style={{ marginTop: '8px' }}>Open Applications →</button>
            </div>

            <div className="card admin-nav-card" onClick={() => onNavigate('adminProviders')} style={{ cursor: 'pointer' }}>
              <p className="eyebrow">Integrations</p>
              <h3>Department Providers ({overview.providers.registered})</h3>
              <p className="muted">Department health, capabilities and outage testing.</p>
              <button className="small outline" style={{ marginTop: '8px' }}>Inspect Providers →</button>
            </div>

            <div className="card admin-nav-card" onClick={() => onNavigate('adminAlerts')} style={{ cursor: 'pointer' }}>
              <p className="eyebrow">Interventions</p>
              <h3>Exceptions & Alerts ({overview.exceptions.activeProviderIncidents + overview.exceptions.totalAlerts})</h3>
              <p className="muted">Incidents, fallback activity, failed jobs and pending reviews.</p>
              <button className="small outline" style={{ marginTop: '8px' }}>View Exceptions →</button>
            </div>

            <div className="card admin-nav-card" onClick={() => onNavigate('audit')} style={{ cursor: 'pointer' }}>
              <p className="eyebrow">Accountability</p>
              <h3>Audit trail</h3>
              <p className="muted">{overview.system.auditEntriesCount} tamper-evident events recorded.</p>
              <button className="small outline" style={{ marginTop: '8px' }}>View Ledger →</button>
            </div>
          </div>

          {/* Asynchronous Worker & Pipeline Status */}
          <div className="card" style={{ marginBottom: '24px' }}>
            <div className="section-heading">
              <div>
                <h2>Background jobs</h2>
                <p>Queued and retried department requests.</p>
              </div>
              <span className="count-badge">Total Jobs: {overview.jobs?.total || 0}</span>
            </div>

            <div className="metric-row">
              <span><b>{overview.jobs?.counts?.QUEUED || 0}</b> Queued</span>
              <span><b>{overview.jobs?.counts?.RUNNING || 0}</b> Running</span>
              <span><b>{overview.jobs?.counts?.COMPLETED || 0}</b> Completed</span>
              <span><b>{overview.jobs?.counts?.FAILED || 0}</b> Failed</span>
              <span style={{ background: overview.jobs?.counts?.DEAD_LETTER > 0 ? '#fff0df' : '#F5DFDB' }}>
                <b style={{ color: overview.jobs?.counts?.DEAD_LETTER > 0 ? '#a25a12' : '#127475' }}>
                  {overview.jobs?.counts?.DEAD_LETTER || 0}
                </b> Dead Letter
              </span>
              <span><b>{overview.jobs?.retryCount || 0}</b> Retries Executed</span>
            </div>
          </div>

          {/* Recent Operational Jobs Stream */}
          <div className="card">
            <div className="section-heading">
              <div>
                <h2>Recent department requests</h2>
                <p>Latest department requests.</p>
              </div>
              <button className="small outline" onClick={() => onNavigate('adminAlerts')}>
                Inspect Dead-Letter Queue
              </button>
            </div>

            {recentJobs.length === 0 ? (
              <p className="muted">No recent provider jobs recorded.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Job ID</th>
                      <th>Type</th>
                      <th>Application</th>
                      <th>Provider</th>
                      <th>Attempts</th>
                      <th>Status</th>
                      <th>Outcome / Error</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentJobs.map(job => (
                      <tr key={job.jobId}>
                        <td><code>{job.jobId.slice(0, 16)}…</code></td>
                        <td>{job.type}</td>
                        <td>
                          {job.applicationId ? (
                            <button
                              className="link-button"
                              style={{ background: 'none', border: 'none', color: '#127475', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}
                              onClick={() => onNavigate('adminApplicationDetail', job.applicationId)}
                            >
                              {job.applicationId}
                            </button>
                          ) : '—'}
                        </td>
                        <td><b>{job.providerId || 'System'}</b></td>
                        <td>{job.attempt} / {job.maxAttempts}</td>
                        <td>
                          <span className={`status ${job.status === 'COMPLETED' ? 'found' : job.status === 'DEAD_LETTER' ? 'exception' : 'pending'}`}>
                            {job.status}
                          </span>
                        </td>
                        <td>
                          {job.error ? (
                            <span style={{ color: '#a25a12' }}>
                              [{job.error.category}] {job.error.message?.slice(0, 40)}
                            </span>
                          ) : (
                            <span style={{ color: '#0B6E6D' }}>✓ Verified</span>
                          )}
                        </td>
                        <td><small>{new Date(job.createdAt).toLocaleTimeString()}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* Reset environment modal (refused by the backend in production mode) */}
      {resetOpen && (
        <div className="modal-backdrop" role="presentation">
          <section className="reset-modal" role="dialog" aria-modal="true" aria-labelledby="admin-reset-title">
            <span className="modal-icon">!</span>
            <p className="eyebrow">Admin Action</p>
            <h2 id="admin-reset-title">Reset this environment?</h2>
            <p>
              This clears all applications, documents, consent receipts, notifications, provider jobs, incidents,
              events and audit history. Seeded accounts, citizens, schemes and providers are kept.
              This action is refused in production environments.
            </p>
            <div className="actions">
              <button className="outline" onClick={() => setResetOpen(false)}>Cancel</button>
              <button className="primary danger-button" onClick={handleResetDemo}>Reset environment</button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
