import { useEffect, useState } from 'react';

export default function IntegrationHealthPage({ onHealth, onReset }) {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [resetOpen, setResetOpen] = useState(false);
  const refresh = () => {
    setLoading(true);
    onHealth().then(setHealth).catch(err => setError(err.message)).finally(() => setLoading(false));
  };
  useEffect(refresh, []);
  async function resetDemo() {
    try { await onReset(); window.location.reload(); } catch (err) { setError(err.message); setResetOpen(false); }
  }
  return <main className="container">
    <div className="page-title"><div><p className="eyebrow">Interoperability operations · admin</p><h1>Integration health</h1><p>Live status of the simulated department adapters used by the platform.</p></div><div className="actions"><button className="outline" onClick={refresh} disabled={loading}>{loading ? 'Checking…' : 'Refresh health'}</button><button className="outline danger-text" onClick={() => setResetOpen(true)}>Reset demo</button></div></div>
    {error && <div className="alert danger">Unable to retrieve integration health: {error}</div>}
    {health && <div className="card"><table><thead><tr><th>Department / system</th><th>Adapter</th><th>Service</th><th>Status</th><th>Last checked</th><th>Response</th></tr></thead><tbody>{health.integrations.map(item => <tr key={item.system}><td><b>{item.department}</b></td><td>{item.adapterType}</td><td>{item.service}</td><td><strong className={item.status === 'AVAILABLE' ? 'good' : 'warn'}>{item.status}</strong></td><td>{new Date(item.lastCheckedAt).toLocaleString()}</td><td>{item.error || 'Ready'}</td></tr>)}</tbody></table></div>}
    {resetOpen && <div className="modal-backdrop" role="presentation"><section className="reset-modal" role="dialog" aria-modal="true" aria-labelledby="reset-title"><span className="modal-icon">!</span><p className="eyebrow">Admin action</p><h2 id="reset-title">Reset demonstration environment?</h2><p>This clears the current in-memory applications, consent receipts, notifications, events and audit history, then restores deterministic demo defaults.</p><div className="actions"><button className="outline" onClick={() => setResetOpen(false)}>Cancel</button><button className="primary danger-button" onClick={resetDemo}>Reset demo</button></div></section></div>}
  </main>;
}
