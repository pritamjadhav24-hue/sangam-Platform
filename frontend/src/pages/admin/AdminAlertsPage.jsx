import { useEffect, useState } from 'react';
import { Skeleton } from '../../components/ui';

export default function AdminAlertsPage({ onNavigateToApplication, api }) {
  const [incidents, setIncidents] = useState([]);
  const [deadLetterJobs, setDeadLetterJobs] = useState([]);
  const [mappingReviews, setMappingReviews] = useState([]);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [replayingId, setReplayingId] = useState(null);
  const [actioningId, setActioningId] = useState(null);
  const [notice, setNotice] = useState('');
  const [impactOpen, setImpactOpen] = useState(null);
  const [impactDetail, setImpactDetail] = useState({});

  const loadData = () => {
    setLoading(true);
    setError('');
    Promise.all([
      api.adminIncidents(),
      api.adminDeadLetterJobs(50),
      api.adminSchemaMappingReviews().catch(() => ({ reviews: [] })),
      api.adminOverview(),
    ])
      .then(([incidentsRes, jobsRes, reviewsRes, overviewRes]) => {
        setIncidents(incidentsRes.incidents || []);
        setDeadLetterJobs(jobsRes.jobs || []);
        setMappingReviews((reviewsRes.reviews || []).filter(r => r.status === 'WAITING_FOR_OFFICER'));
        setOverview(overviewRes);
      })
      .catch(err => setError(err.message || 'Failed to load exceptions.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  async function handleReplay(jobId) {
    setReplayingId(jobId);
    setNotice('');
    setError('');
    try {
      await api.adminReplayJob(jobId);
      setNotice(`Job ${jobId} re-queued for retry.`);
      loadData();
    } catch (err) {
      setError(err.message || 'Failed to replay job.');
    } finally {
      setReplayingId(null);
    }
  }

  async function toggleImpact(incidentId) {
    if (impactOpen === incidentId) { setImpactOpen(null); return; }
    setImpactOpen(incidentId);
    try {
      const detail = await api.adminIncidentImpact(incidentId);
      setImpactDetail(current => ({ ...current, [incidentId]: detail }));
    } catch (err) {
      setImpactDetail(current => ({ ...current, [incidentId]: { error: err.message || 'Impact could not be loaded.' } }));
    }
  }

  async function handleMappingDecision(reviewId, decision) {
    setActioningId(reviewId);
    setNotice('');
    setError('');
    try {
      await api.adminSchemaMappingAction(reviewId, decision, `Resolved by administrator (${decision}).`);
      setNotice(`Schema mapping review ${reviewId} marked ${decision}.`);
      loadData();
    } catch (err) {
      setError(err.message || 'Failed to record decision.');
    } finally {
      setActioningId(null);
    }
  }

  const entityReviewCount = overview?.exceptions?.entityReviews || 0;
  const conflictReviewCount = overview?.exceptions?.conflictReviews || 0;

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Incidents & Exceptions</h1>
          <p>Cases that need investigation.</p>
        </div>
        <div className="actions">
          <button className="outline" onClick={loadData} disabled={loading}>
            {loading ? 'Refreshing…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}
      {notice && <div className="alert success" role="alert">{notice}</div>}

      <div className="summary-grid" style={{ marginBottom: '24px' }}>
        <div className={`summary-card ${incidents.some(i => i.status === 'OPEN') ? 'amber' : ''}`}>
          <span className="eyebrow">Active Provider Incidents</span>
          <b>{incidents.filter(i => i.status === 'OPEN').length}</b>
          <small>System/provider-level outages, distinct from individual dead-letter jobs</small>
        </div>
        <div className="summary-card amber">
          <span className="eyebrow">Dead-Letter Jobs</span>
          <b>{deadLetterJobs.length}</b>
          <small>Provider dispatches that exhausted automated retries</small>
        </div>
        <div className="summary-card amber">
          <span className="eyebrow">Identity Match Reviews</span>
          <b>{entityReviewCount}</b>
          <small>Unresolved identity-matching cases (see Application Registry)</small>
        </div>
        <div className="summary-card amber">
          <span className="eyebrow">Conflict Reviews</span>
          <b>{conflictReviewCount}</b>
          <small>Unreconciled conflicting records (see Application Registry)</small>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <div>
            <h2>Provider Incidents</h2>
            <p>One incident per department outage, with the applications it affected.</p>
          </div>
          <span className="count-badge">Open: {incidents.filter(i => i.status === 'OPEN').length}</span>
        </div>

        {loading ? (
          <Skeleton lines={4} label="Loading incidents" />
        ) : incidents.length === 0 ? (
          <div className="empty-state">
            <span>✓</span>
            <h3>No provider incidents recorded</h3>
            <p className="muted">All providers have been healthy.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '12px', marginTop: '12px' }}>
            {incidents.map(incident => (
              <div
                key={incident.incidentId}
                className="incident-card"
                style={{
                  border: '1px solid #E8D5D0', borderRadius: '6px', padding: '14px',
                  borderLeft: `4px solid ${incident.status === 'OPEN' ? '#F2542D' : '#0E9594'}`,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', alignItems: 'flex-start' }}>
                  <div>
                    <b>{incident.department}</b>{incident.service ? <span className="muted"> — {incident.service}</span> : null}
                    <div style={{ marginTop: '4px' }}>
                      <span className={`status ${incident.status === 'OPEN' ? 'exception' : 'found'}`}>
                        {incident.status === 'OPEN' ? 'DOWN' : 'RESOLVED'}
                      </span>
                      {incident.errorCategory && <small style={{ marginLeft: '8px', color: '#7A6360' }}>[{incident.errorCategory}]</small>}
                    </div>
                    <small style={{ display: 'block', marginTop: '6px', color: '#7A6360' }}>
                      Detected {new Date(incident.detectedAt).toLocaleString()}
                      {incident.resolvedAt && ` · Resolved ${new Date(incident.resolvedAt).toLocaleString()}`}
                    </small>
                  </div>
                  <div className="incident-impact-counts" aria-label="Incident impact">
                    <div><b>{incident.affectedCitizens ?? 0}</b> affected citizen{incident.affectedCitizens === 1 ? '' : 's'}</div>
                    <div><b>{incident.affectedApplications}</b> affected application{incident.affectedApplications === 1 ? '' : 's'}</div>
                    <div><b>{(incident.affectedSchemes || []).length}</b> affected scheme{(incident.affectedSchemes || []).length === 1 ? '' : 's'}</div>
                    <div style={{ color: incident.blockedOperations > 0 ? '#a25a12' : '#7A6360' }}><b>{incident.blockedOperations ?? 0}</b> blocked operation{incident.blockedOperations === 1 ? '' : 's'}</div>
                    <div className="muted"><b>{incident.pendingRetries ?? incident.retryPendingCount ?? 0}</b> pending retr{(incident.pendingRetries ?? 0) === 1 ? 'y' : 'ies'}</div>
                    <div style={{ color: '#0B6E6D' }}><b>{incident.successfulFallbacks ?? incident.fallbackRecoveredCount ?? 0}</b> successful fallback{incident.successfulFallbacks === 1 ? '' : 's'}</div>
                    <div style={{ color: '#0B6E6D' }}><b>{incident.recoveredApplications ?? 0}</b> recovered application{incident.recoveredApplications === 1 ? '' : 's'}</div>
                  </div>
                </div>
                {(incident.affectedSchemes || []).length > 0 && (
                  <small className="muted" style={{ display: 'block', marginTop: '8px' }}>Schemes: {incident.affectedSchemes.join(', ')}</small>
                )}
                {incident.affectedApplications > 0 && (
                  <button className="small outline" style={{ marginTop: '10px' }} onClick={() => toggleImpact(incident.incidentId)} aria-expanded={impactOpen === incident.incidentId}>
                    {impactOpen === incident.incidentId ? 'Hide affected applications' : 'View affected applications'}
                  </button>
                )}
                {impactOpen === incident.incidentId && (
                  <IncidentImpactTable detail={impactDetail[incident.incidentId]} onNavigateToApplication={onNavigateToApplication} />
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <div>
            <h2>Dead-Letter Provider Jobs</h2>
            <p>Retries were exhausted for these requests. Replay once the department is available.</p>
          </div>
          <span className="count-badge">Jobs: {deadLetterJobs.length}</span>
        </div>

        {loading ? (
          <Skeleton lines={4} label="Loading exceptions" />
        ) : deadLetterJobs.length === 0 ? (
          <div className="empty-state">
            <span>✓</span>
            <h3>No dead-letter jobs</h3>
            <p className="muted">No failed requests.</p>
          </div>
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
                  <th>Failure Reason</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {deadLetterJobs.map(job => (
                  <tr key={job.jobId}>
                    <td><code>{job.jobId.slice(0, 16)}…</code></td>
                    <td>{job.type}</td>
                    <td>
                      {job.applicationId ? (
                        <button
                          className="link-button"
                          style={{ background: 'none', border: 'none', color: '#127475', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}
                          onClick={() => onNavigateToApplication(job.applicationId)}
                        >
                          {job.applicationId}
                        </button>
                      ) : '—'}
                    </td>
                    <td><b>{job.providerId || 'System'}</b></td>
                    <td>{job.attempt} / {job.maxAttempts}</td>
                    <td>
                      {job.error ? (
                        <span style={{ color: '#a25a12' }}>[{job.error.category}] {job.error.message?.slice(0, 60)}</span>
                      ) : '—'}
                    </td>
                    <td>
                      <button
                        className="small outline"
                        onClick={() => handleReplay(job.jobId)}
                        disabled={replayingId === job.jobId}
                      >
                        {replayingId === job.jobId ? 'Replaying…' : 'Replay Job'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="section-heading">
          <div>
            <h2>Schema Mapping Reviews</h2>
            <p>Field mappings that need a decision.</p>
          </div>
          <span className="count-badge">Reviews: {mappingReviews.length}</span>
        </div>

        {mappingReviews.length === 0 ? (
          <div className="empty-state">
            <span>✓</span>
            <h3>No pending schema mapping reviews</h3>
            <p className="muted">No mapping reviews pending.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '12px', marginTop: '12px' }}>
            {mappingReviews.map(review => (
              <div key={review.reviewId} style={{ border: '1px solid #E8D5D0', borderRadius: '6px', padding: '14px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                  <div>
                    <b>{review.mapping?.sourceSystem}: {review.mapping?.sourceField}</b>
                    <small style={{ display: 'block', color: '#7A6360' }}>
                      Suggested canonical field: {review.mapping?.canonicalField || 'Ambiguous'} · Confidence: {review.mapping?.confidence ?? '—'} ({review.mapping?.confidenceLevel})
                    </small>
                    {review.mapping?.evidence && <small style={{ display: 'block', color: '#7A6360' }}>{review.mapping.evidence}</small>}
                  </div>
                  <div className="actions">
                    <button className="small outline" disabled={actioningId === review.reviewId} onClick={() => handleMappingDecision(review.reviewId, 'REJECT')}>
                      Reject
                    </button>
                    <button className="small primary" disabled={actioningId === review.reviewId} onClick={() => handleMappingDecision(review.reviewId, 'APPROVE')}>
                      {actioningId === review.reviewId ? 'Saving…' : 'Approve'}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}


function IncidentImpactTable({ detail, onNavigateToApplication }) {
  if (!detail) return <Skeleton lines={4} label="Loading affected applications" />;
  if (detail.error) return <div className="alert danger" role="alert">{detail.error}</div>;
  if (!detail.applications?.length) return <p className="muted">No applications depended on this provider during the incident.</p>;
  return (
    <div style={{ overflowX: 'auto', marginTop: '10px' }}>
      <table>
        <thead>
          <tr><th>Application</th><th>Citizen</th><th>Scheme</th><th>Blocked stage</th><th>Requirements</th></tr>
        </thead>
        <tbody>
          {detail.applications.map(app => (
            <tr key={app.appId}>
              <td>
                <button className="link-button" style={{ background: 'none', border: 'none', color: '#127475', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}
                  onClick={() => onNavigateToApplication(app.appId)}>{app.appId}</button>
                <small style={{ display: 'block' }} className="muted">{app.applicationStatus}</small>
              </td>
              <td>{app.citizenId || '—'}</td>
              <td>{app.schemeName || '—'}</td>
              <td>{app.blockedStage || (app.recovered ? 'Recovered' : 'Not blocked')}</td>
              <td>
                {app.requirements.map(req => (
                  <div key={req.requirementCode}>
                    <b>{req.label}</b>: {req.stateLabel}{req.resolvedBy ? ` — ${req.resolvedBy}` : ''}
                  </div>
                ))}
                {app.jobs.map(job => <div key={job.jobId} className="muted">Job {job.jobId.slice(0, 12)}…: {job.status}</div>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
