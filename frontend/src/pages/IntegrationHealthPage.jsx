import { useEffect, useState } from 'react';

export default function IntegrationHealthPage({ onHealth, onReset }) {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const refresh = () => {
    setLoading(true);
    onHealth().then(setHealth).catch(err => setError(err.message)).finally(() => setLoading(false));
  };
  useEffect(refresh, []);
  async function resetDemo() {
    if (!window.confirm('Reset the in-memory demo? Applications, consent, notifications, events, and audit history will be cleared.')) return;
    try { await onReset(); window.location.reload(); } catch (err) { setError(err.message); }
  }
  return <main className="container">
    <div className="page-title"><div><p className="eyebrow">Interoperability operations · admin</p><h1>Integration health</h1><p>Live status of the simulated department adapters used by the platform.</p></div><div className="actions"><button className="outline" onClick={refresh} disabled={loading}>{loading ? 'Checking…' : 'Refresh health'}</button><button className="outline danger-text" onClick={resetDemo}>Reset demo</button></div></div>
    {error && <div className="alert danger">Unable to retrieve integration health: {error}</div>}
    {health && <div className="card"><table><thead><tr><th>Department / system</th><th>Adapter</th><th>Service</th><th>Status</th><th>Last checked</th><th>Response</th></tr></thead><tbody>{health.integrations.map(item => <tr key={item.system}><td><b>{item.department}</b></td><td>{item.adapterType}</td><td>{item.service}</td><td><strong className={item.status === 'AVAILABLE' ? 'good' : 'warn'}>{item.status}</strong></td><td>{new Date(item.lastCheckedAt).toLocaleString()}</td><td>{item.error || 'Ready'}</td></tr>)}</tbody></table></div>}
  </main>;
}
