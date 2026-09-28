import { useEffect, useState } from 'react';
import { applicationStateClass, applicationStateLabel } from '../../applicationState';
import { requirementStateClass, requirementStateLabel } from '../../requirementState';
import { ActivityTimeline, StatusPill, Skeleton } from '../../components/ui';

const DEPARTMENT_NAMES = { REVENUE: 'Revenue Department', EDUCATION: 'Education Department', SOCIAL_WELFARE: 'Social Welfare Department', MUNICIPAL_HEALTH: 'Health Department', TRANSPORT: 'Transport Department', IDENTITY: 'State Resident Registry' };

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
        <Skeleton lines={4} label="Loading application orchestration state" />
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
            <p className="eyebrow">Application</p>
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

      <EligibilityAssessment eligibility={detail.eligibility} />

      {/* Requirements Orchestration Matrix */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <div>
            <h2>Requirement Orchestration & Source Selection</h2>
            <p>Data source and verification result for each requirement.</p>
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
                      {req.isFallback && (
                        <span className="tag" style={{ fontSize: '11px', background: '#fff0df', color: '#a25a12' }}>
                          ⇄ Fallback Provider Used
                        </span>
                      )}
                      {req.mandatory && (
                        <small style={{ color: '#C8401C', fontWeight: 600 }}>Mandatory</small>
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

                {/* Orchestration Lineage: the requirement's story as an ordered
                    step trail, derived from its own persisted fields. */}
                {req.lineageSteps && req.lineageSteps.length > 0 && (
                  <div style={{ marginTop: '12px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '4px', fontSize: '12px' }}>
                    {req.lineageSteps.map((step, idx) => (
                      <span key={idx} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        <span
                          title={step.detail}
                          style={{ padding: '3px 8px', borderRadius: '10px', background: '#F5DFDB', color: '#562C2C', whiteSpace: 'nowrap' }}
                        >
                          {step.step}
                        </span>
                        {idx < req.lineageSteps.length - 1 && <span style={{ color: '#C9A9A3' }}>→</span>}
                      </span>
                    ))}
                  </div>
                )}

                {(req.sourceDepartment || req.identityMatch) && (
                  <div className="identity-match">
                    {req.sourceDepartment && <span><b>Verified by:</b> {DEPARTMENT_NAMES[req.sourceDepartment] || req.sourceDepartment}{req.verifiedAt ? ` · ${new Date(req.verifiedAt).toLocaleString()}` : ''}</span>}
                    {req.identityMatch && (
                      <span>
                        <b>Record match:</b> {req.identityMatch.confidenceLevel} ({Math.round((req.identityMatch.score || 0) * 100)}%) —
                        {' '}{req.identityMatch.decision === 'AUTO_ACCEPT' ? 'same person' : 'not confirmed, record not attached'}
                        {' '}· matched {(req.identityMatch.matchedFields || []).join(', ') || 'no fields'}
                        {(req.identityMatch.fieldComparisons || []).filter(item => item.field === 'address' && item.candidateNormalized).map(item => (
                          <small key="address" className="muted" style={{ display: 'block' }}>Address normalised: "{item.sourceNormalized}" vs "{item.candidateNormalized}" ({Math.round(item.score * 100)}%)</small>
                        ))}
                      </span>
                    )}
                  </div>
                )}

                {/* Full provenance, for administrators (citizens see only the department). */}
                {req.provenance && (
                  <dl className="provenance-grid">
                    <div><dt>Provider</dt><dd><code>{req.provenance.providerId}</code></dd></div>
                    <div><dt>Source record</dt><dd><code>{req.provenance.sourceRecordId || '—'}</code></dd></div>
                    <div><dt>Verified</dt><dd>{req.provenance.verifiedAt ? new Date(req.provenance.verifiedAt).toLocaleString() : '—'}</dd></div>
                    <div><dt>Method</dt><dd>{String(req.provenance.verificationMethod || '').replace(/_/g, ' ').toLowerCase()} · {req.provenance.recordKind === 'DOCUMENT' ? 'department document' : 'structured record'}</dd></div>
                    <div><dt>Found by department</dt><dd>{String(req.provenance.departmentMatchMethod || 'n/a').replace(/_/g, ' ').toLowerCase()}</dd></div>
                    <div><dt>Match</dt><dd><StatusPill status={req.provenance.matchCategory === 'EXACT' || req.provenance.matchCategory === 'STRONG' ? 'VERIFIED' : 'WARNING'} label={`${req.provenance.matchCategory || 'Unchecked'}${typeof req.provenance.confidence === 'number' ? ` · ${Math.round(req.provenance.confidence * 100)}%` : ''}`} /></dd></div>
                    <div><dt>Role</dt><dd><StatusPill status={req.provenance.authorizationRole || 'AUTHORITATIVE'} label={req.provenance.fallbackUsed ? 'Authorized fallback' : 'Authoritative source'} /></dd></div>
                  </dl>
                )}
                {req.trace?.steps?.length > 0 && (
                  <details className="trace-details">
                    <summary>SANGAM exchange: {req.trace.consumerDepartment || 'application'} → SANGAM → {req.trace.targetDepartment || 'no department answered'} ({req.trace.steps.length} steps)</summary>
                    <ActivityTimeline steps={req.trace.steps} />
                  </details>
                )}

                {/* Primary provider's open incident, when the fallback that
                    fulfilled this requirement was triggered by one. */}
                {req.primaryProviderIncident && (
                  <div style={{ marginTop: '10px', padding: '8px 12px', background: '#fff0f0', borderLeft: '3px solid #F2542D', fontSize: '12px' }}>
                    <b>Primary Provider Incident:</b> {req.primaryProvider} has been DOWN since{' '}
                    {new Date(req.primaryProviderIncident.detectedAt).toLocaleString()}
                    {req.primaryProviderIncident.errorCategory && <span> · [{req.primaryProviderIncident.errorCategory}]</span>}
                  </div>
                )}

                {/* Source Selection & Explainable Decision */}
                <div style={{ marginTop: '12px', padding: '10px 12px', background: '#FBF3F1', borderRadius: '4px', fontSize: '13px' }}>
                  <b>Source Selection Decision:</b>
                  <p style={{ margin: '4px 0 6px', color: '#562C2C' }}>
                    {req.decisionReason || 'Selected from the providers registered for this requirement.'}
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
                              color: c.isChosen ? '#0B6E6D' : '#7A6360',
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
          <p className="muted">No background jobs for this application.</p>
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
                        <span style={{ color: '#0B6E6D' }}>✓ None</span>
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

const ELIGIBILITY_RESULT = {
  ELIGIBLE: ['Eligible', 'found'],
  NOT_ELIGIBLE: ['Not eligible', 'exception'],
  CANNOT_CONFIRM: ['Cannot be confirmed yet', 'pending'],
  NOT_ASSESSED: ['No eligibility rules configured', 'pending'],
};

// Deterministic rule outcome plus data completeness; the confidence level
// describes data quality only and never overrides the rule result.
function EligibilityAssessment({ eligibility }) {
  if (!eligibility) return null;
  const [label, className] = ELIGIBILITY_RESULT[eligibility.result] || [eligibility.result, 'pending'];
  const completeness = eligibility.completeness || {};
  return (
    <div className="card" style={{ marginBottom: '24px' }}>
      <div className="section-heading">
        <div>
          <h2>Eligibility Assessment</h2>
          <p>Scheme rules checked against verified information.</p>
        </div>
        <span className={`status ${className}`}>{label}</span>
      </div>
      <div className="summary-grid" style={{ margin: '12px 0' }}>
        <div className="summary-card"><span className="eyebrow">Failed rules</span><b>{eligibility.failedCriteria?.length || 0}</b><small>{(eligibility.failedCriteria || []).join(', ') || 'None'}</small></div>
        <div className="summary-card"><span className="eyebrow">Undetermined rules</span><b>{eligibility.unknownCriteria?.length || 0}</b><small>{eligibility.conflict ? 'Open conflict/review on this application' : 'Missing, unverified or expired data'}</small></div>
        <div className="summary-card"><span className="eyebrow">Data completeness</span><b>{(completeness.verifiedByProvider || 0) + (completeness.providedByCitizen || 0)}/{completeness.total || 0}</b>
          <small>{completeness.verifiedByProvider || 0} provider-verified · {completeness.providedByCitizen || 0} citizen-uploaded · {completeness.pending || 0} pending · {completeness.notProvided || 0} not provided · {completeness.failed || 0} failed</small></div>
        <div className="summary-card"><span className="eyebrow">Confidence (data quality)</span><b>{eligibility.confidence || '—'}</b><small>{eligibility.confidenceReason}</small></div>
      </div>
      {eligibility.criteria?.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead><tr><th>Rule</th><th>Result</th><th>Observed</th><th>Data source</th><th>Reason</th></tr></thead>
            <tbody>
              {eligibility.criteria.map(item => (
                <tr key={item.id}>
                  <td><b>{item.label}</b><small style={{ display: 'block' }} className="muted">{item.type}{item.requirementCode ? ` · ${item.requirementCode}` : ''}</small></td>
                  <td><span className={`status ${item.status === 'PASS' ? 'found' : item.status === 'FAIL' ? 'exception' : 'pending'}`}>{item.status}</span></td>
                  <td>{item.observed ?? '—'}</td>
                  <td>{{ VERIFIED: 'Provider-verified', MANUAL: 'Citizen upload', PROFILE: 'Identity record' }[item.source] || '—'}</td>
                  <td>{item.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
