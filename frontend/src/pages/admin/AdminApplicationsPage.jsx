import { useEffect, useState } from 'react';
import { applicationStateClass, applicationStateLabel } from '../../applicationState';

const STATUS_FILTERS = [
  { key: 'ALL', label: 'All Statuses' },
  { key: 'IN_PROGRESS', label: 'In Progress' },
  { key: 'SUBMITTED', label: 'Submitted' },
  { key: 'WAITING_FOR_OFFICER', label: 'Waiting for Officer' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
];

export default function AdminApplicationsPage({ onSelectApplication, api }) {
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchApplications = () => {
    setLoading(true);
    setError('');
    api.adminApplications({
      status: statusFilter === 'ALL' ? undefined : statusFilter,
      search: searchTerm.trim() || undefined,
      limit: 100,
    })
      .then(res => setApplications(res.applications || []))
      .catch(err => setError(err.message || 'Failed to fetch applications.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchApplications();
  }, [statusFilter]);

  function handleSearchSubmit(e) {
    e.preventDefault();
    fetchApplications();
  }

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">Registry & Tracking · Admin</p>
          <h1>Platform Applications</h1>
          <p>Complete operational registry of all citizen applications and their current orchestration states.</p>
        </div>
        <div className="actions">
          <button className="outline" onClick={fetchApplications} disabled={loading}>
            {loading ? 'Refreshing…' : '↻ Refresh List'}
          </button>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}

      {/* Search and Filters */}
      <div className="card" style={{ marginBottom: '20px' }}>
        <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            type="search"
            placeholder="Search by Application ID (e.g. APP-...) or Citizen ID..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            style={{ flex: '1', minWidth: '260px' }}
          />
          <button type="submit" className="primary" disabled={loading}>
            Search
          </button>
          {searchTerm && (
            <button
              type="button"
              className="outline"
              onClick={() => { setSearchTerm(''); setTimeout(fetchApplications, 0); }}
            >
              Clear
            </button>
          )}
        </form>

        <div className="category-filters" style={{ marginTop: '16px' }}>
          {STATUS_FILTERS.map(f => (
            <button
              key={f.key}
              type="button"
              className={`chip ${statusFilter === f.key ? 'selected' : ''}`}
              onClick={() => setStatusFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Applications Table */}
      <div className="card">
        <div className="section-heading">
          <h2>Application Registry</h2>
          <span className="count-badge">Found: {applications.length} applications</span>
        </div>

        {loading ? (
          <p className="loading-state">Loading applications from PostgreSQL authority…</p>
        ) : applications.length === 0 ? (
          <div className="empty-state">
            <span>○</span>
            <h3>No applications match the selected criteria</h3>
            <p className="muted">Try adjusting the search query or status filter.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Application ID</th>
                  <th>Citizen ID</th>
                  <th>Service / Scheme</th>
                  <th>Status</th>
                  <th>Requirements Progress</th>
                  <th>Processing Nature</th>
                  <th>Created</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {applications.map(app => (
                  <tr key={app.appId}>
                    <td>
                      <code>{app.appId}</code>
                    </td>
                    <td>
                      <b>{app.citizenId}</b>
                    </td>
                    <td>
                      <span>{app.schemeName}</span>
                      <small>{app.serviceId}</small>
                    </td>
                    <td>
                      <span className={`status ${applicationStateClass(app.status)}`}>
                        {applicationStateLabel(app.status, 'en')}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontWeight: 600, color: app.fulfilledCount === app.requirementsCount ? '#0E9594' : '#127475' }}>
                        {app.fulfilledCount} / {app.requirementsCount}
                      </span>
                      <small>fulfilled</small>
                    </td>
                    <td>
                      {app.hasException ? (
                        <span className="status exception" title="Contains exceptions, missing records, or human intervention">
                          ⚠ Needs Attention
                        </span>
                      ) : (
                        <span className="status found" title="Standard automated cross-department verification">
                          ✓ Automated
                        </span>
                      )}
                    </td>
                    <td>
                      <small>{app.createdAt ? new Date(app.createdAt).toLocaleDateString() : '—'}</small>
                    </td>
                    <td>
                      <button
                        className="small outline"
                        onClick={() => onSelectApplication(app.appId)}
                        title="View requirement-level orchestration and provider execution details"
                      >
                        Inspect Orchestration →
                      </button>
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
