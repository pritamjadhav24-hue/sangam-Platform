import { useEffect, useState } from 'react';
import { applicationStateClass, applicationStateLabel } from '../../applicationState';
import { requirementStateClass, requirementStateLabel } from '../../requirementState';

export default function AdminApplicationDetailPage({ applicationId, onBack, api }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadDetail = () => {
    setLoading(true);
    setError('');
    api.adminApplicationDetail(applicationId)
      .then(setDetail)
      .catch(err => setError(err.message || 'Failed to load application detail.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (applicationId) loadDetail();
  }, [applicationId]);

  if (loading) {
    return (
      <main className="container">
        <button className="outline small back-link" onClick={onBack}>← Back to Applications</button>
        <p className="loading-state">Loading application orchestration state…</p>
      </main>
    );
  }

  if (error || !detail) {
    return (
      <main className="container">
        <button className="outline small back-link" onClick={onBack}>← Back to Applications</button>
        <div className="alert danger" role="alert">{error || 'Application not found.'}</div>
      </main>
    );
  }

  return (
    <main className="container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <button className="outline small back-link" onClick={onBack} style={{ margin: 0 }}>
          ← Back to Applications
        </button>
        <button className="outline small" onClick={loadDetail}>
          ↻ Refresh Orchestration
        </button>
      </div>

      {/* Header Card */}
      <div className="card" style={{ marginBottom: '24px', borderLeft: '4px solid #127475' }}>
        <div className="page-title" style={{ marginBottom: '12px' }}>
          <div>
            <p className="eyebrow">Orchestration & Verification Trace</p>
            <h1 style={{ fontSize: '26px' }}>{detail.schemeName}</h1>
            <p>Application ID: <code>{detail.appId}</code> · Citizen ID: <code>{detail.citizenId}</code></p>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span className={`status ${applicationStateClass(detail.status)}`} style={{ fontSize: '14px', padding: '6px 12px' }}>
              {applicationStateLabel(detail.status, 'en')}
            </span>
            <small style={{ display: 'block', marginTop: '6px', color: '#7A6360' }}>
              Created: {detail.createdAt ? new Date(detail.createdAt).toLocaleString() : '—'}
            </small>
          </div>
        </div>

        {/* Workflow Lifecycle History */}
        {detail.statusHistory && detail.statusHistory.length > 0 && (
          <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #E8D5D0' }}>
            <span className="eyebrow" style={{ fontSize: '11px' }}>Status Lifecycle Transitions</span>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '6px' }}>
              {detail.statusHistory.map((h, i) => (
                <span key={i} className="status pending" style={{ fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                  <b>{h.status}</b>
                  <small>({h.actor} · {new Date(h.at).toLocaleTimeString()})</small>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Requirements Orchestration Matrix */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <div>
            <h2>Requirement Orchestration & Source Selection</h2>
            <p>Automated provider selection, source-decision transparency, and verification outcome per requirement.</p>
          </div>
          <span className="count-badge">
            {detail.requirements.filter(r => ['VALIDATED', 'RETRIEVED', 'USER_OVERRIDDEN'].includes(r.status)).length} / {detail.requirements.length} Satisfied
          </span>
        </div>

        <div style={{ display: 'grid', gap: '16px', marginTop: '16px' }}>
          {detail.requirements.map(req => {
            const isSuccess = ['VALIDATED', 'RETRIEVED'].includes(req.status);
            const isManual = req.fulfillmentMethod === 'MANUAL_UPLOAD';
            const isException = ['ACTION_REQUIRED', 'FAILED', 'REJECTED'].includes(req.status);

            return (
              <div
                key={req.code}
                style={{
                  border: '1px solid #E8D5D0',
                  borderRadius: '6px',
                  padding: '16px',
                  background: isSuccess ? '#FAFCFB' : isException ? '#FFFBF8' : '#fff',
                  borderLeft: `4px solid ${isSuccess ? '#0E9594' : isException ? '#F2542D' : '#127475'}`,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '8px' }}>
                  <div>
                    <span className="eyebrow" style={{ fontSize: '11px' }}>Code: {req.code}</span>
                    <h3 style={{ margin: '2px 0 6px', color: '#562C2C' }}>{req.label}</h3>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <span className={`status ${requirementStateClass(req.status)}`}>
                        {requirementStateLabel(req.status, 'en')}
                      </span>
                      <span className="tag" style={{ fontSize: '11px' }}>
                        Method: {req.fulfillmentMethod}
                      </span>
                      {req.mandatory && (
                        <small style={{ color: '#F2542D', fontWeight: 600 }}>Mandatory</small>
                      )}
                    </div>
                  </div>

                  {req.resultReference && (
                    <div style={{ textAlign: 'right' }}>
                      <small style={{ color: '#7A6360' }}>Result Reference ID</small>
                      <div><code>{req.resultReference}</code></div>
                    </div>
                  )}
                </div>

                {/* Source Selection & Explainable Decision */}
                <div style={{ marginTop: '12px', padding: '10px 12px', background: '#FBF3F1', borderRadius: '4px', fontSize: '13px' }}>
                  <b>Source Selection Decision:</b>
                  <p style={{ margin: '4px 0 6px', color: '#562C2C' }}>
                    {req.decisionReason || 'Provider discovery evaluated against registered capabilities.'}
                  </p>

                  {/* Candidates tier hierarchy */}
                  {req.sourceCandidates && req.sourceCandidates.length > 0 && (
                    <div style={{ marginTop: '8px' }}>
                      <small style={{ display: 'block', color: '#7A6360', marginBottom: '4px' }}>Eligible Provider Hierarchy:</small>
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        {req.sourceCandidates.map((c, idx) => (
                          <span
                            key={idx}
                            style={{
                              padding: '3px 8px',
                              borderRadius: '3px',
                              fontSize: '11px',
                              background: c.isChosen ? '#daf1e7' : '#fff',
                              border: `1px solid ${c.isChosen ? '#0E9594' : '#E8D5D0'}`,
                              color: c.isChosen ? '#0E9594' : '#7A6360',
                              fontWeight: c.isChosen ? 700 : 400,
                            }}
                          >
                            Priority {c.priority}: {c.provider} ({c.healthStatus}) {c.isChosen ? '★ Selected' : ''}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Verified Canonical Attributes */}
                {req.canonical && Object.keys(req.canonical).length > 0 && (
                  <div style={{ marginTop: '12px' }}>
                    <small style={{ fontWeight: 700, color: '#127475' }}>Verified Canonical Attributes:</small>
                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '6px' }}>
                      {Object.entries(req.canonical).map(([key, val]) => (
                        <div key={key} style={{ background: '#F5DFDB', padding: '4px 8px', borderRadius: '3px', fontSize: '12px' }}>
                          <span style={{ color: '#7A6360' }}>{key}: </span>
                          <b style={{ color: '#562C2C' }}>{String(val)}</b>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Entity Resolution / Review info if present */}
                {req.entityReview && (
                  <div style={{ marginTop: '10px', padding: '8px 12px', background: '#fffaf0', borderLeft: '3px solid #d19a35', fontSize: '12px' }}>
                    <b>Entity Resolution Check:</b> Confidence Level: <code>{req.entityReview.confidenceLevel}</code> ({req.entityReview.confidenceScore})
                    {req.entityReview.decision && <span> · Decision: <b>{req.entityReview.decision}</b></span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Asynchronous Dependencies & Provider Jobs */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <h2>Asynchronous Execution & Provider Jobs</h2>
          <span className="count-badge">Jobs: {detail.jobs.length}</span>
        </div>

        {detail.jobs.length === 0 ? (
          <p className="muted">No asynchronous background provider jobs were dispatched for this application (synchronous execution or direct retrieval).</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Type</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Error / Failure Reason</th>
                  <th>Completed At</th>
                </tr>
              </thead>
              <tbody>
                {detail.jobs.map(j => (
                  <tr key={j.jobId}>
                    <td><code>{j.jobId}</code></td>
                    <td>{j.type}</td>
                    <td><b>{j.providerId}</b></td>
                    <td>
                      <span className={`status ${j.status === 'COMPLETED' ? 'found' : j.status === 'DEAD_LETTER' ? 'exception' : 'pending'}`}>
                        {j.status}
                      </span>
                    </td>
                    <td>{j.attempt} / {j.maxAttempts}</td>
                    <td>
                      {j.error ? (
                        <span style={{ color: '#a25a12' }}>[{j.error.category}] {j.error.message}</span>
                      ) : (
                        <span style={{ color: '#0E9594' }}>✓ None</span>
                      )}
                    </td>
                    <td><small>{j.completedAt ? new Date(j.completedAt).toLocaleString() : 'In Progress'}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Correlated Audit Entries for this Application */}
      <div className="card">
        <div className="section-heading">
          <h2>Application Audit Lineage</h2>
          <span className="count-badge">Entries: {detail.auditEntries.length}</span>
        </div>

        {detail.auditEntries.length === 0 ? (
          <p className="muted">No correlated audit entries recorded for this application identifier.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Actor / Role</th>
                  <th>Action</th>
                  <th>Target / Source</th>
                  <th>Nature</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {detail.auditEntries.map(e => {
                  const isAutomated = ['SYSTEM', 'GovOrchestrator', 'PROVIDER'].includes(e.who) || !e.who?.startsWith('OFFICER');
                  return (
                    <tr key={e.sequence || Math.random()}>
                      <td>{e.sequence}</td>
                      <td>
                        <b>{e.who}</b>
                        <small>{e.payload?.actorRole || (isAutomated ? 'Middleware Engine' : 'Human Officer')}</small>
                      </td>
                      <td>{e.action || e.what}</td>
                      <td><code>{e.source}</code></td>
                      <td>
                        <span className={`status ${isAutomated ? 'found' : 'pending'}`}>
                          {isAutomated ? 'Automated' : 'Human Intervention'}
                        </span>
                      </td>
                      <td><small>{new Date(e.when).toLocaleString()}</small></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
