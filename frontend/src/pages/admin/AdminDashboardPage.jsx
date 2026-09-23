import { useEffect, useState } from 'react';

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
          <p className="eyebrow">Middleware Operations · Admin Console</p>
          <h1>Operations Dashboard</h1>
          <p>Real-time system health, cross-department orchestration, and exception monitoring across SANGAM.</p>
        </div>
        <div className="actions">
          <button className="outline" onClick={loadData} disabled={loading}>
            {loading ? 'Refreshing…' : '↻ Refresh Data'}
          </button>
          <button className="outline danger-text" onClick={() => setResetOpen(true)}>
            Reset Demo Environment
          </button>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}

      {overview && (
        <>
          {/* Top Operational Metrics */}
          <div className="summary-grid">
            <div className="summary-card">
              <span className="eyebrow">System State</span>
              <b>{overview.system.postgres === 'CONNECTED' ? 'Operational' : 'Degraded'}</b>
              <small>
                Ledger Chain: {overview.system.auditChainValid ? '✓ Verified' : '⚠ Invalid'} · Zero Centralization: Enforced
              </small>
            </div>

            <div className="summary-card blue">
              <span className="eyebrow">Total Applications</span>
              <b>{overview.applications.total}</b>
              <small>
                {overview.applications.automaticallyVerified} Verified Auto · {overview.applications.requiringAttention} Need Attention
              </small>
            </div>

            <div className="summary-card">
              <span className="eyebrow">Department Providers</span>
              <b>{overview.providers.available} / {overview.providers.total}</b>
              <small>
                {overview.providers.degraded === 0 ? 'All 10 sandboxes available' : `${overview.providers.degraded} degraded/offline`}
              </small>
            </div>

            <div className={`summary-card ${overview.exceptions.totalAlerts > 0 ? 'amber' : ''}`}>
              <span className="eyebrow">Active Exceptions</span>
              <b>{overview.exceptions.totalAlerts}</b>
              <small>
                {overview.exceptions.deadLetterJobs} Dead-letter · {overview.exceptions.entityReviews + overview.exceptions.conflictReviews} Reviews
              </small>
            </div>
          </div>

          {/* Quick Navigation Cards */}
          <div className="admin-quick-nav grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', marginBottom: '24px' }}>
            <div className="card admin-nav-card" onClick={() => onNavigate('adminApplications')} style={{ cursor: 'pointer' }}>
              <p className="eyebrow">Registry</p>
              <h3>Applications ({overview.applications.total})</h3>
              <p className="muted">Search all applications, inspect orchestration lineage, and track verification stages.</p>
              <button className="small outline" style={{ marginTop: '8px' }}>Open Applications →</button>
            </div>

            <div className="card admin-nav-card" onClick={() => onNavigate('adminProviders')} style={{ cursor: 'pointer' }}>
              <p className="eyebrow">Integrations</p>
              <h3>Department Providers ({overview.providers.total})</h3>
              <p className="muted">Inspect department adapter health, capabilities, and test resilience simulation.</p>
              <button className="small outline" style={{ marginTop: '8px' }}>Inspect Providers →</button>
            </div>

            <div className="card admin-nav-card" onClick={() => onNavigate('adminAlerts')} style={{ cursor: 'pointer' }}>
              <p className="eyebrow">Interventions</p>
              <h3>Exceptions & Alerts ({overview.exceptions.totalAlerts})</h3>
              <p className="muted">Monitor dead-letter jobs, replay failed dispatches, and review ambiguities.</p>
              <button className="small outline" style={{ marginTop: '8px' }}>View Exceptions →</button>
            </div>

            <div className="card admin-nav-card" onClick={() => onNavigate('audit')} style={{ cursor: 'pointer' }}>
              <p className="eyebrow">Accountability</p>
              <h3>Audit & Data Lineage</h3>
              <p className="muted">{overview.system.auditEntriesCount} SHA-256 chained events recording automated vs officer actions.</p>
              <button className="small outline" style={{ marginTop: '8px' }}>View Ledger →</button>
            </div>
          </div>

          {/* Asynchronous Worker & Pipeline Status */}
          <div className="card" style={{ marginBottom: '24px' }}>
            <div className="section-heading">
              <div>
                <h2>Asynchronous Orchestration Pipeline</h2>
                <p>Background provider jobs, leasing status, and automated retry metrics.</p>
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
                <h2>Recent Operational Jobs</h2>
                <p>Latest asynchronous requests processed across integrated department sandboxes.</p>
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
                            <span style={{ color: '#0E9594' }}>✓ Verified</span>
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

      {/* Reset Demo Modal */}
      {resetOpen && (
        <div className="modal-backdrop" role="presentation">
          <section className="reset-modal" role="dialog" aria-modal="true" aria-labelledby="admin-reset-title">
            <span className="modal-icon">!</span>
            <p className="eyebrow">Admin Action</p>
            <h2 id="admin-reset-title">Reset demonstration environment?</h2>
            <p>
              This clears all in-memory applications, consent receipts, notifications, events, and audit history,
              restoring clean deterministic defaults.
            </p>
            <div className="actions">
              <button className="outline" onClick={() => setResetOpen(false)}>Cancel</button>
              <button className="primary danger-button" onClick={handleResetDemo}>Reset Demo</button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
