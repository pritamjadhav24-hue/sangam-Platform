import { useEffect, useState } from 'react';

export default function AdminProviderDetailPage({ providerId, onBack, onNavigateToApplication, api }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadDetail = () => {
    setLoading(true);
    setError('');
    api.adminProviderDetail(providerId)
      .then(setDetail)
      .catch(err => setError(err.message || 'Failed to load provider detail.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (providerId) loadDetail();
  }, [providerId]);

  if (loading) {
    return (
      <main className="container">
        <button className="outline small back-link" onClick={onBack}>← Back to Providers</button>
        <p className="loading-state">Loading provider detail…</p>
      </main>
    );
  }

  if (error || !detail) {
    return (
      <main className="container">
        <button className="outline small back-link" onClick={onBack}>← Back to Providers</button>
        <div className="alert danger" role="alert">{error || 'Provider not found.'}</div>
      </main>
    );
  }

  const healthy = detail.health?.status === 'AVAILABLE' || detail.health?.status === 'HEALTHY';
  const openIncident = detail.incidents?.find(i => i.status === 'OPEN');

  return (
    <main className="container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <button className="outline small back-link" onClick={onBack} style={{ margin: 0 }}>← Back to Providers</button>
        <button className="outline small" onClick={loadDetail}>↻ Refresh</button>
      </div>

      {/* Overview */}
      <div className="card" style={{ marginBottom: '24px', borderLeft: `4px solid ${healthy ? '#0E9594' : '#F2542D'}` }}>
        <div className="page-title" style={{ marginBottom: '12px' }}>
          <div>
            <p className="eyebrow">Provider Overview</p>
            <h1 style={{ fontSize: '26px' }}>{detail.department || detail.name}</h1>
            <p>Provider ID: <code>{detail.providerId}</code> · Adapter: <code>{detail.adapterType}</code></p>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span className={`status ${healthy ? 'found' : 'exception'}`} style={{ fontSize: '14px', padding: '6px 12px' }}>
              {detail.health?.status}
            </span>
            {openIncident && (
              <small style={{ display: 'block', marginTop: '6px', color: '#F2542D' }}>
                Incident open since {new Date(openIncident.detectedAt).toLocaleString()}
              </small>
            )}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', marginTop: '12px', paddingTop: '12px', borderTop: '1px solid #E8D5D0' }}>
          <div><small className="muted">Environment</small><div><b>{detail.environment}</b></div></div>
          <div><small className="muted">Auth Type</small><div><b>{detail.authType || 'NONE'}</b></div></div>
          <div><small className="muted">Contract Version</small><div><b>{detail.contractVersion || 'v1'}</b></div></div>
          <div><small className="muted">Timeout</small><div><b>{detail.timeoutSeconds}s</b></div></div>
          <div><small className="muted">Max Attempts</small><div><b>{detail.maxAttempts}</b></div></div>
          <div><small className="muted">Active</small><div><b>{detail.active ? 'Yes' : 'No'}</b></div></div>
          <div><small className="muted">Last Success</small><div><b>{detail.health?.lastSuccessAt ? new Date(detail.health.lastSuccessAt).toLocaleString() : '—'}</b></div></div>
          <div><small className="muted">Last Failure</small><div><b>{detail.health?.lastFailureAt ? new Date(detail.health.lastFailureAt).toLocaleString() : '—'}</b></div></div>
        </div>
      </div>

      {/* Capabilities */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <h2>Capabilities & Requirement Mappings</h2>
          <span className="count-badge">{detail.capabilities.length} capabilities</span>
        </div>
        {detail.capabilities.length === 0 ? (
          <p className="muted">No capabilities registered for this provider.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr><th>Requirement Code</th><th>Service</th><th>Priority</th><th>Current Health</th></tr>
              </thead>
              <tbody>
                {detail.capabilities.map(c => (
                  <tr key={c.requirementCode}>
                    <td><code>{c.requirementCode}</code></td>
                    <td>{c.serviceName} <small className="muted">{c.serviceId}</small></td>
                    <td>{c.priority}</td>
                    <td><span className={`status ${c.healthStatus === 'AVAILABLE' || c.healthStatus === 'HEALTHY' ? 'found' : 'exception'}`}>{c.healthStatus}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Schema Mapping Status */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <h2>Schema Mapping Status</h2>
          <span className="count-badge">{detail.schemaMappings.length} mappings</span>
        </div>
        {detail.schemaMappings.length === 0 ? (
          <p className="muted">No persisted department-field → canonical-field mappings for this provider.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr><th>Department Field</th><th>Canonical Field</th><th>Data Type</th><th>Service</th></tr>
              </thead>
              <tbody>
                {detail.schemaMappings.map((m, idx) => (
                  <tr key={idx}>
                    <td><code>{m.departmentField}</code></td>
                    <td><code>{m.canonicalField}</code></td>
                    <td>{m.dataType}</td>
                    <td><small className="muted">{m.serviceId}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Reliability / Recent Jobs */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <div>
            <h2>Reliability</h2>
            <p>{detail.reliability.successCount} succeeded · {detail.reliability.failureCount} failed</p>
          </div>
          <span className="count-badge">Recent Jobs: {detail.reliability.recentJobs.length}</span>
        </div>
        {detail.reliability.recentJobs.length === 0 ? (
          <p className="muted">No asynchronous provider jobs recorded for this provider.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr><th>Job ID</th><th>Type</th><th>Application</th><th>Status</th><th>Created</th></tr>
              </thead>
              <tbody>
                {detail.reliability.recentJobs.map(j => (
                  <tr key={j.jobId}>
                    <td><code>{j.jobId.slice(0, 16)}…</code></td>
                    <td>{j.type}</td>
                    <td>
                      {j.applicationId ? (
                        <button
                          className="link-button"
                          style={{ background: 'none', border: 'none', color: '#127475', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}
                          onClick={() => onNavigateToApplication?.(j.applicationId)}
                        >
                          {j.applicationId}
                        </button>
                      ) : '—'}
                    </td>
                    <td><span className={`status ${j.status === 'COMPLETED' ? 'found' : j.status === 'DEAD_LETTER' ? 'exception' : 'pending'}`}>{j.status}</span></td>
                    <td><small>{new Date(j.createdAt).toLocaleString()}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Provider Incidents */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <h2>Provider Incidents</h2>
          <span className="count-badge">{detail.incidents.length}</span>
        </div>
        {detail.incidents.length === 0 ? (
          <p className="muted">No incidents recorded for this provider.</p>
        ) : (
          <div style={{ display: 'grid', gap: '10px', marginTop: '10px' }}>
            {detail.incidents.map(i => (
              <div key={i.incidentId} style={{ border: '1px solid #E8D5D0', borderRadius: '6px', padding: '10px 14px', borderLeft: `3px solid ${i.status === 'OPEN' ? '#F2542D' : '#0E9594'}` }}>
                <span className={`status ${i.status === 'OPEN' ? 'exception' : 'found'}`}>{i.status}</span>
                <small style={{ marginLeft: '8px', color: '#7A6360' }}>
                  Detected {new Date(i.detectedAt).toLocaleString()}
                  {i.resolvedAt && ` · Resolved ${new Date(i.resolvedAt).toLocaleString()}`}
                </small>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Relevant Audit Events */}
      <div className="card">
        <div className="section-heading">
          <h2>Relevant Audit Events</h2>
          <span className="count-badge">{detail.auditEvents.length}</span>
        </div>
        {detail.auditEvents.length === 0 ? (
          <p className="muted">No audit ledger entries have this provider as their source yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr><th>#</th><th>Who</th><th>Action</th><th>Why</th><th>Timestamp</th></tr>
              </thead>
              <tbody>
                {[...detail.auditEvents].reverse().map(e => (
                  <tr key={e.sequence}>
                    <td>{e.sequence}</td>
                    <td>{e.who}</td>
                    <td><span className="tag" style={{ fontSize: '11px' }}>{e.action}</span></td>
                    <td>{e.why}</td>
                    <td><small>{new Date(e.when).toLocaleString()}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
