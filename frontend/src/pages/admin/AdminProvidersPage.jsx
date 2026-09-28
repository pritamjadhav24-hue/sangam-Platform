import { useEffect, useMemo, useState } from 'react';
import DepartmentHealthPanel from './DepartmentHealthPanel';
import { Skeleton } from '../../components/ui';

export default function AdminProvidersPage({ api, onOpenProvider }) {
  const [providers, setProviders] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [simSystem, setSimSystem] = useState('');
  const [simAvailable, setSimAvailable] = useState(false);
  const [simError, setSimError] = useState('Upstream sandbox simulated timeout');
  const [simLoading, setSimLoading] = useState(false);
  const [simSuccess, setSimSuccess] = useState('');
  const [departmentRefresh, setDepartmentRefresh] = useState(0);

  const loadProviders = () => {
    setLoading(true);
    setError('');
    Promise.all([
      api.adminProviderRegistry(),
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

  // Provider <-> Requirement capability matrix, built client-side from the
  // same registry data (no separate backend endpoint / no second
  // provider-selection algorithm) -- every provider already lists its own
  // real capabilities from the existing capability catalog.
  const requirementCodes = useMemo(() => {
    const codes = new Set();
    providers.forEach(p => (p.capabilities || []).forEach(c => codes.add(c.requirementCode)));
    return Array.from(codes).sort();
  }, [providers]);

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
          <p className="eyebrow">Operations</p>
          <h1>Department Providers & System Health</h1>
          <p>
            Department systems, providers and their current health.
          </p>
        </div>
        <div className="actions">
          <button className="outline" onClick={() => { loadProviders(); setDepartmentRefresh(count => count + 1); }} disabled={loading}>
            {loading ? 'Refreshing…' : '↻ Refresh Status'}
          </button>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}

      <DepartmentHealthPanel api={api} onChanged={loadProviders} refreshToken={departmentRefresh} />
      {simSuccess && <div className="alert success" role="alert">{simSuccess}</div>}

      {/* Integration Providers Table */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="section-heading">
          <div>
            <h2>Provider / Integration Registry</h2>
            <p>Registered providers with their capabilities, health and incidents.</p>
          </div>
          <span className="count-badge">Total Providers: {providers.length}</span>
        </div>

        {loading ? (
          <Skeleton lines={4} label="Loading provider registry" />
        ) : providers.length === 0 ? (
          <div className="empty-state">
            <span>○</span>
            <h3>No providers registered</h3>
            <p className="muted">The provider capability catalog is empty.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Department / Provider</th>
                  <th>Capabilities (Requirements)</th>
                  <th>Adapter</th>
                  <th>Auth</th>
                  <th>Status</th>
                  <th>Incident</th>
                  <th>Reliability</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {providers.map(p => {
                  const status = p.health?.status || (p.active ? 'AVAILABLE' : 'UNAVAILABLE');
                  const isAvailable = status === 'AVAILABLE' || status === 'HEALTHY';
                  return (
                    <tr key={p.providerId || p.name}>
                      <td>
                        <b>{p.department || p.name}</b>
                        <small>{p.providerId}</small>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', maxWidth: '220px' }}>
                          {(p.capabilities || []).map(c => (
                            <span key={c.requirementCode} className="tag" style={{ fontSize: '10px' }} title={`Priority ${c.priority}`}>
                              {c.requirementCode}
                            </span>
                          ))}
                          {(p.capabilities || []).length === 0 && <small className="muted">None</small>}
                        </div>
                      </td>
                      <td><code>{p.adapterType}</code></td>
                      <td><span className="tag" style={{ fontSize: '11px' }}>{p.authType || 'NONE'}</span></td>
                      <td>
                        <span className={`status ${isAvailable ? 'found' : 'exception'}`}>
                          {status}
                        </span>
                      </td>
                      <td>
                        {p.activeIncident ? (
                          <span className="status exception" title={`Detected ${new Date(p.activeIncident.detectedAt).toLocaleString()}`}>DOWN</span>
                        ) : (
                          <span style={{ color: '#7A6360' }}>—</span>
                        )}
                      </td>
                      <td>
                        <small style={{ color: '#0B6E6D' }}>✓ {p.successCount || 0}</small>
                        {p.failureCount > 0 && (
                          <small style={{ color: '#C8401C', display: 'block' }}>⚠ {p.failureCount}</small>
                        )}
                      </td>
                      <td>
                        <button className="small outline" onClick={() => onOpenProvider?.(p.providerId)}>
                          View Detail →
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Provider <-> Requirement Capability Matrix */}
      {!loading && providers.length > 0 && requirementCodes.length > 0 && (
        <div className="card" style={{ marginBottom: '24px' }}>
          <div className="section-heading">
            <div>
              <h2>Provider ↔ Requirement Capability Matrix</h2>
              <p>Which providers can answer each requirement, and in what order.</p>
            </div>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Requirement</th>
                  <th>Eligible Providers (priority order)</th>
                </tr>
              </thead>
              <tbody>
                {requirementCodes.map(code => {
                  const eligible = providers
                    .map(p => ({ p, cap: (p.capabilities || []).find(c => c.requirementCode === code) }))
                    .filter(item => item.cap)
                    .sort((a, b) => (a.cap.priority || 100) - (b.cap.priority || 100));
                  return (
                    <tr key={code}>
                      <td><code>{code}</code></td>
                      <td>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                          {eligible.map(({ p, cap }, idx) => {
                            const healthy = (p.health?.status === 'AVAILABLE' || p.health?.status === 'HEALTHY');
                            return (
                              <span
                                key={p.providerId}
                                className="tag"
                                style={{ fontSize: '11px', background: healthy ? '#F5DFDB' : '#fff0df', color: healthy ? '#10696A' : '#a25a12' }}
                              >
                                {idx === 0 ? '★ ' : ''}{p.name} (P{cap.priority})
                              </span>
                            );
                          })}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Fault injection: admin-only resilience testing controls */}
      <div className="card" style={{ borderLeft: '4px solid #F2542D' }}>
        <div className="section-heading">
          <div>
            <p className="eyebrow" style={{ color: '#C8401C' }}>Administrator tool · Fault injection</p>
            <h2>Fault-Tolerance & Resilience Testing</h2>
            <p>
              Mark a provider unavailable to test fallback and incident handling. For test environments only.</p>
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
              <span style={{ color: '#C8401C', fontWeight: 600 }}>Simulate Outage (UNAVAILABLE)</span>
            </label>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                type="radio"
                name="simAvailable"
                checked={simAvailable}
                onChange={() => setSimAvailable(true)}
              />
              <span style={{ color: '#0B6E6D', fontWeight: 600 }}>Restore Normal (AVAILABLE)</span>
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
