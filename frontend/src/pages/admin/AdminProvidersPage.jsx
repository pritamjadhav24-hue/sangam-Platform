import { useEffect, useState } from 'react';

export default function AdminProvidersPage({ api }) {
  const [providers, setProviders] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [simSystem, setSimSystem] = useState('');
  const [simAvailable, setSimAvailable] = useState(false);
  const [simError, setSimError] = useState('Upstream sandbox simulated timeout');
  const [simLoading, setSimLoading] = useState(false);
  const [simSuccess, setSimSuccess] = useState('');

  const loadProviders = () => {
    setLoading(true);
    setError('');
    Promise.all([
      api.adminProviders(),
      api.integrationHealth(),
    ])
      .then(([provRes, healthRes]) => {
        setProviders(provRes.providers || []);
        setIntegrations(healthRes.integrations || []);
        if (healthRes.integrations?.length > 0 && !simSystem) {
          setSimSystem(healthRes.integrations[0].system);
        }
      })
      .catch(err => setError(err.message || 'Failed to load provider registry.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadProviders();
  }, []);

  async function handleSimulate(e) {
    e.preventDefault();
    if (!simSystem) return;
    setSimLoading(true);
    setSimSuccess('');
    setError('');
    try {
      const res = await api.adminSimulateHealth(simSystem, simAvailable, simAvailable ? null : simError);
      setSimSuccess(`Updated simulated state for ${simSystem} to ${res.status || (simAvailable ? 'AVAILABLE' : 'UNAVAILABLE')}.`);
      loadProviders();
    } catch (err) {
      setError(err.message || 'Failed to update simulation state.');
    } finally {
      setSimLoading(false);
    }
  }

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">Federated Middleware Integrations · Admin</p>
          <h1>Department Providers & System Health</h1>
          <p>
            SANGAM serves as interoperability middleware. Department databases remain the authoritative source of truth.
          </p>
        </div>
        <div className="actions">
          <button className="outline" onClick={loadProviders} disabled={loading}>
            {loading ? 'Refreshing…' : '↻ Refresh Status'}
          </button>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}
      {simSuccess && <div className="alert success" role="alert">{simSuccess}</div>}

      {/* Integration Providers Table */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <div>
            <h2>Integrated Department Providers</h2>
            <p>Simulated Maharashtra state department databases connected via REST & catalog adapters.</p>
          </div>
          <span className="count-badge">Total Providers: {providers.length}</span>
        </div>

        {loading ? (
          <p className="loading-state">Loading provider status…</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Department / System</th>
                  <th>Adapter Type</th>
                  <th>Contract</th>
                  <th>Auth</th>
                  <th>Status</th>
                  <th>Reliability Metrics</th>
                  <th>Last Failure Category</th>
                </tr>
              </thead>
              <tbody>
                {providers.map(p => {
                  const status = p.health?.status || (p.enabled ? 'AVAILABLE' : 'UNAVAILABLE');
                  const isAvailable = status === 'AVAILABLE' || status === 'HEALTHY';
                  return (
                    <tr key={p.providerId || p.name}>
                      <td>
                        <b>{p.name}</b>
                        <small>{p.providerId || 'Provider ID not assigned'}</small>
                      </td>
                      <td><code>{p.adapterType}</code></td>
                      <td>{p.contractVersion || 'v1'}</td>
                      <td><span className="tag" style={{ fontSize: '11px' }}>{p.authType || 'NONE'}</span></td>
                      <td>
                        <span className={`status ${isAvailable ? 'found' : 'exception'}`}>
                          {status}
                        </span>
                      </td>
                      <td>
                        <small style={{ color: '#0E9594' }}>✓ {p.successCount || 0} succeeded</small>
                        {p.failureCount > 0 && (
                          <small style={{ color: '#F2542D', display: 'block' }}>⚠ {p.failureCount} failed</small>
                        )}
                      </td>
                      <td>
                        {p.errorCategory ? (
                          <span style={{ color: '#a25a12' }}>[{p.errorCategory}]</span>
                        ) : (
                          <span style={{ color: '#7A6360' }}>None</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Protected Resilience Demonstration Controls */}
      <div className="card" style={{ borderLeft: '4px solid #F2542D' }}>
        <div className="section-heading">
          <div>
            <p className="eyebrow" style={{ color: '#F2542D' }}>Protected Demonstration Capability · SIH 2026</p>
            <h2>Fault-Tolerance & Resilience Testing</h2>
            <p>
              Simulate an upstream department outage or latency spike to demonstrate how SANGAM gracefully
              falls back to alternate provider candidates without crashing the citizen experience.
            </p>
          </div>
        </div>

        <form onSubmit={handleSimulate} style={{ display: 'grid', gap: '16px', maxWidth: '650px', marginTop: '14px' }}>
          <div>
            <label style={{ display: 'block', fontWeight: 600, color: '#562C2C', marginBottom: '6px' }}>
              Target Department System
            </label>
            <select
              value={simSystem}
              onChange={e => setSimSystem(e.target.value)}
              style={{ width: '100%', padding: '10px', border: '1px solid #E8D5D0', borderRadius: '4px' }}
            >
              {integrations.map(item => (
                <option key={item.system} value={item.system}>
                  {item.department || item.system} ({item.status})
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                type="radio"
                name="simAvailable"
                checked={!simAvailable}
                onChange={() => setSimAvailable(false)}
              />
              <span style={{ color: '#F2542D', fontWeight: 600 }}>Simulate Outage (UNAVAILABLE)</span>
            </label>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                type="radio"
                name="simAvailable"
                checked={simAvailable}
                onChange={() => setSimAvailable(true)}
              />
              <span style={{ color: '#0E9594', fontWeight: 600 }}>Restore Normal (AVAILABLE)</span>
            </label>
          </div>

          {!simAvailable && (
            <div>
              <label style={{ display: 'block', fontWeight: 600, color: '#562C2C', marginBottom: '6px' }}>
                Simulated Error Reason
              </label>
              <input
                type="text"
                value={simError}
                onChange={e => setSimError(e.target.value)}
                placeholder="e.g. Gateway timeout or 503 service unavailable"
                style={{ width: '100%', padding: '10px', border: '1px solid #E8D5D0', borderRadius: '4px' }}
              />
            </div>
          )}

          <div>
            <button type="submit" className="primary" disabled={simLoading}>
              {simLoading ? 'Applying…' : 'Apply Simulation State'}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}
