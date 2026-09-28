import { useEffect, useState } from 'react';
import { Skeleton } from '../../components/ui';

export default function AdminSchemesPage({ api, onOpenScheme }) {
  const [schemes, setSchemes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = () => {
    setLoading(true);
    setError('');
    api.adminSchemes()
      .then(res => setSchemes(res.schemes || []))
      .catch(err => setError(err.message || 'Failed to load the scheme catalogue.'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Schemes &amp; Requirements</h1>
          <p>Scheme definitions and each requirement's provider coverage.</p>
        </div>
        <div className="actions">
          <button className="outline" onClick={load} disabled={loading}>{loading ? 'Refreshing…' : '↻ Refresh'}</button>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}

      <div className="card">
        <div className="section-heading">
          <h2>Scheme catalogue</h2>
          <span className="count-badge">Schemes: {schemes.length}</span>
        </div>
        {loading ? (
          <Skeleton lines={4} label="Loading scheme catalogue" />
        ) : schemes.length === 0 ? (
          <div className="empty-state">
            <span>○</span>
            <h3>No schemes configured</h3>
            <p className="muted">The scheme catalogue table is empty.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Scheme</th>
                  <th>Department</th>
                  <th>State</th>
                  <th>Requirements</th>
                  <th>Provider coverage</th>
                  <th>Applications</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {schemes.map(scheme => {
                  const uncovered = scheme.requirementCount - scheme.providerCoverage;
                  return (
                    <tr key={scheme.schemeId}>
                      <td>
                        <b>{scheme.name}</b>
                        <small><code>{scheme.schemeId}</code>{scheme.category ? ` · ${scheme.category}` : ''}</small>
                      </td>
                      <td>{scheme.department}</td>
                      <td>
                        <span className={`status ${scheme.active ? 'found' : 'exception'}`}>{scheme.active ? 'ACTIVE' : 'INACTIVE'}</span>
                        {scheme.synthetic && <small className="muted">Synthetic data</small>}
                      </td>
                      <td>{scheme.requirementCount} <small className="muted">{scheme.mandatoryCount} mandatory</small></td>
                      <td>
                        {scheme.providerCoverage} / {scheme.requirementCount}
                        {uncovered > 0 && <small style={{ color: '#a25a12' }}>{uncovered} manual-upload only</small>}
                      </td>
                      <td>{scheme.applicationCount}</td>
                      <td><button className="small outline" onClick={() => onOpenScheme(scheme.schemeId)}>View Detail →</button></td>
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
