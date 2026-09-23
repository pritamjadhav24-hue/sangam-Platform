import { useEffect, useState } from 'react';

export default function AdminAlertsPage({ onNavigateToApplication, api }) {
  const [deadLetterJobs, setDeadLetterJobs] = useState([]);
  const [mappingReviews, setMappingReviews] = useState([]);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [replayingId, setReplayingId] = useState(null);
  const [actioningId, setActioningId] = useState(null);
  const [notice, setNotice] = useState('');

  const loadData = () => {
    setLoading(true);
    setError('');
    Promise.all([
      api.adminDeadLetterJobs(50),
      api.adminSchemaMappingReviews().catch(() => ({ reviews: [] })),
      api.adminOverview(),
    ])
      .then(([jobsRes, reviewsRes, overviewRes]) => {
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
          <p className="eyebrow">Exception Monitoring · Admin</p>
          <h1>Exceptions & Alerts</h1>
          <p>Genuine cases requiring investigation — normal automated retrievals never appear here.</p>
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
        <div className="summary-card amber">
          <span className="eyebrow">Dead-Letter Jobs</span>
          <b>{deadLetterJobs.length}</b>
          <small>Provider dispatches that exhausted automated retries</small>
        </div>
        <div className="summary-card amber">
          <span className="eyebrow">Entity Resolution Reviews</span>
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
            <h2>Dead-Letter Provider Jobs</h2>
            <p>Automated retries were exhausted for these dispatches. Replay after the upstream issue is resolved.</p>
          </div>
          <span className="count-badge">Jobs: {deadLetterJobs.length}</span>
        </div>

        {loading ? (
          <p className="loading-state">Loading exceptions…</p>
        ) : deadLetterJobs.length === 0 ? (
          <div className="empty-state">
            <span>✓</span>
            <h3>No dead-letter jobs</h3>
            <p className="muted">Every provider dispatch has either completed or is still within its retry window.</p>
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
            <p>Semantic field-mapping ambiguities that automated matching could not resolve with confidence.</p>
          </div>
          <span className="count-badge">Reviews: {mappingReviews.length}</span>
        </div>

        {mappingReviews.length === 0 ? (
          <div className="empty-state">
            <span>✓</span>
            <h3>No pending schema mapping reviews</h3>
            <p className="muted">Automated semantic mapping is resolving fields with sufficient confidence.</p>
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
