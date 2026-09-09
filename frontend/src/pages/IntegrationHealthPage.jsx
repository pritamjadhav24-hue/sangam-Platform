import { useEffect, useState } from 'react';

export default function IntegrationHealthPage({ onHealth }) {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const refresh = () => {
    setLoading(true);
    onHealth().then(setHealth).catch(err => setError(err.message)).finally(() => setLoading(false));
  };
  useEffect(refresh, []);
  return <main className="container">
    <div className="page-title"><div><p className="eyebrow">Interoperability operations</p><h1>Integration health</h1><p>Live status of the simulated department adapters used by the platform.</p></div><button className="outline" onClick={refresh} disabled={loading}>{loading ? 'Checking…' : 'Refresh health'}</button></div>
    {error && <div className="alert danger">Unable to retrieve integration health: {error}</div>}
    {health && <div className="card"><table><thead><tr><th>Department / system</th><th>Adapter</th><th>Service</th><th>Status</th><th>Last checked</th><th>Response</th></tr></thead><tbody>{health.integrations.map(item => <tr key={item.system}><td><b>{item.department}</b></td><td>{item.adapterType}</td><td>{item.service}</td><td><strong className={item.status === 'AVAILABLE' ? 'good' : 'warn'}>{item.status}</strong></td><td>{new Date(item.lastCheckedAt).toLocaleString()}</td><td>{item.error || 'Ready'}</td></tr>)}</tbody></table></div>}
  </main>;
}
