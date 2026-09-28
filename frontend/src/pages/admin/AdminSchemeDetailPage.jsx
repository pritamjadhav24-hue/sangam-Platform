import { useEffect, useState } from 'react';
import { Skeleton } from '../../components/ui';

export default function AdminSchemeDetailPage({ api, schemeId, onBack, onOpenProvider }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!schemeId) return;
    setLoading(true);
    setError('');
    api.adminSchemeDetail(schemeId)
      .then(setDetail)
      .catch(err => setError(err.message || 'Failed to load scheme detail.'))
      .finally(() => setLoading(false));
  }, [schemeId]);

  const back = <button className="outline small back-link" onClick={onBack}>← Back to Schemes</button>;

  if (loading) return <main className="container">{back}<Skeleton lines={4} label="Loading scheme detail" /></main>;
  if (error || !detail) return <main className="container">{back}<div className="alert danger" role="alert">{error || 'Scheme not found.'}</div></main>;

  return (
    <main className="container">
      {back}
      <div className="card" style={{ marginBottom: '24px', borderLeft: '4px solid #127475' }}>
        <p className="eyebrow">Scheme Detail</p>
        <h1 style={{ fontSize: '26px' }}>{detail.name}</h1>
        <p><code>{detail.schemeId}</code> · {detail.department}</p>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <span className={`status ${detail.active ? 'found' : 'exception'}`}>{detail.active ? 'ACTIVE' : 'INACTIVE'}</span>
          {detail.category && <span className="tag" style={{ fontSize: '11px' }}>{detail.category}</span>}
          {detail.synthetic && <span className="tag" style={{ fontSize: '11px' }}>Synthetic data</span>}
          <span className="tag" style={{ fontSize: '11px' }}>{detail.applicationCount} application(s)</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px', marginTop: '16px' }}>
          {[['Description', detail.description], ['Eligibility', detail.eligibility], ['Benefits', detail.benefits], ['Application window', detail.applicationWindow]].map(([label, value]) => (
            <div key={label}>
              <small className="muted">{label}</small>
              <p style={{ margin: '2px 0 0', color: '#562C2C' }}>{value || '—'}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="section-heading">
          <div>
            <h2>Requirements</h2>
            <p>Providers that can answer each requirement. Without one, the citizen uploads the document.</p>
          </div>
          <span className="count-badge">{detail.requirements.length} requirements</span>
        </div>
        {detail.requirements.length === 0 ? (
          <p className="muted">This scheme has no configured requirements.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Requirement</th>
                  <th>Type</th>
                  <th>Required</th>
                  <th>Capability</th>
                  <th>Eligible providers (priority order)</th>
                </tr>
              </thead>
              <tbody>
                {detail.requirements.map(req => (
                  <tr key={req.requirementCode}>
                    <td>
                      <b>{req.label}</b>
                      <small><code>{req.requirementCode}</code>{req.category ? ` · ${req.category}` : ''}</small>
                      {req.description && <small className="muted">{req.description}</small>}
                    </td>
                    <td>{req.dataType || <small className="muted">Not in requirement vocabulary</small>}</td>
                    <td>{req.mandatory ? 'Mandatory' : 'Optional'}</td>
                    <td><code>{req.capability}</code></td>
                    <td>
                      {req.manualUploadOnly ? (
                        <span className="status exception">No eligible provider — manual upload only</span>
                      ) : (
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                          {req.eligibleProviders.map((provider, index) => (
                            <button
                              key={provider.providerId}
                              type="button"
                              className="small outline"
                              title={`Service ${provider.serviceName} · health ${provider.healthStatus}`}
                              onClick={() => onOpenProvider(provider.providerId)}
                            >
                              {index === 0 ? '★ ' : ''}{provider.provider} (P{provider.priority}, {provider.healthStatus})
                            </button>
                          ))}
                        </div>
                      )}
                    </td>
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
