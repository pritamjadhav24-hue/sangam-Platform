import { useEffect, useState } from 'react';
import { Activity, CircleAlert, CircleCheck, CircleX, Clock, RefreshCw, Server, Shuffle, Users } from 'lucide-react';
import { Skeleton, useToast } from '../../components/ui';

// Each department's health on its own, next to the SANGAM platform's. A
// department outage is that department's state -- never the platform's.
const STATUS = {
  AVAILABLE: { label: 'Available', className: 'found', Icon: CircleCheck },
  DEGRADED: { label: 'Degraded', className: 'pending', Icon: CircleAlert },
  UNAVAILABLE: { label: 'Unavailable', className: 'exception', Icon: CircleX },
  NOT_CONFIGURED: { label: 'Not configured', className: 'pending', Icon: CircleAlert },
};

function StatusBadge({ status }) {
  const meta = STATUS[status] || STATUS.NOT_CONFIGURED;
  return <span className={`status ${meta.className}`}><meta.Icon size={14} aria-hidden="true" />{meta.label}</span>;
}

const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

function when(iso) {
  if (!iso) return 'No successful verification yet';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

export default function DepartmentHealthPanel({ api, onChanged, refreshToken = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busyKey, setBusyKey] = useState('');
  const [showOthers, setShowOthers] = useState(false);
  const toast = useToast();

  function load() {
    if (!api.adminDepartments) return Promise.resolve();
    setError('');
    return api.adminDepartments().then(setData).catch(err => setError(err.message || 'Department health could not be loaded.'));
  }
  useEffect(() => { load(); }, [refreshToken]);

  async function toggle(department) {
    setBusyKey(department.key);
    setError('');
    try {
      const restoring = Boolean(department.simulatedOutage);
      setData(await api.adminSetDepartmentAvailability(department.key, restoring));
      toast(restoring
        ? { tone: 'success', title: `${department.name} restored`, message: 'SANGAM will use it again for new verifications.' }
        : { tone: 'warning', title: `${department.name} outage simulated`, message: 'SANGAM stays healthy; only authorized fallbacks can answer for this department.' });
      onChanged?.();
    } catch (err) {
      setError(err.message || 'The department state could not be changed.');
    } finally {
      setBusyKey('');
    }
  }

  if (!api.adminDepartments) return null;
  if (error && !data) return <div className="alert danger" role="alert">{error}</div>;
  if (!data) return <Skeleton lines={4} label="Loading department health" />;

  const headline = data.departments.filter(item => item.headline);
  const others = data.departments.filter(item => !item.headline);

  const card = department => (
    <article key={department.key} className={`card department-card status-${department.status.toLowerCase()}`}>
      <div className="department-card-head">
        <div>
          <h3>{department.name}</h3>
          <p className="muted small-text">{department.providers.length} provider{department.providers.length === 1 ? '' : 's'} · own service & database</p>
        </div>
        <StatusBadge status={department.status} />
      </div>
      {department.simulatedOutage && <p className="small-text muted">Outage simulated by an administrator.</p>}
      <dl className="department-stats">
        <div><dt><Activity size={14} aria-hidden="true" />Latency</dt><dd>{department.latencyMs != null ? `${department.latencyMs} ms` : '—'}</dd></div>
        <div><dt><Clock size={14} aria-hidden="true" />Last verification</dt><dd>{when(department.lastSuccessfulVerification)}</dd></div>
        <div><dt><CircleAlert size={14} aria-hidden="true" />Active incidents</dt><dd>{department.activeIncidents}</dd></div>
        <div><dt><Shuffle size={14} aria-hidden="true" />Fallback</dt><dd>served {department.fallbackUsage.servedAsFallback} · triggered {department.fallbackUsage.fallbacksTriggered}</dd></div>
        <div><dt><Users size={14} aria-hidden="true" />Affected</dt><dd>{plural(department.affectedApplications, 'application')} · {plural(department.affectedCitizens, 'citizen')}</dd></div>
      </dl>
      <div className="chip-row" aria-label="Supported requirements">
        {department.providers.flatMap(provider => provider.requirements.map(requirement => (
          <span key={`${provider.providerId}-${requirement.requirementCode}`} className={`chip-static ${requirement.role === 'FALLBACK' ? 'fallback' : ''}`}
            title={provider.name}>{requirement.requirementCode}{requirement.role === 'FALLBACK' ? ' · fallback' : ''}</span>
        )))}
      </div>
      <button className={`small ${department.simulatedOutage ? 'primary' : 'outline danger-text'} button-with-icon`} disabled={busyKey === department.key}
        onClick={() => toggle(department)}>
        <RefreshCw size={14} aria-hidden="true" />{department.simulatedOutage ? 'Restore department' : 'Simulate outage'}
      </button>
    </article>
  );

  return (
    <section className="department-health" aria-labelledby="department-health-title">
      <div className="section-heading">
        <div>
          <h2 id="department-health-title">Department systems</h2>
          <p className="muted">Each department's API and database, monitored independently.</p>
        </div>
        <span className="department-pill platform"><Server size={16} aria-hidden="true" />SANGAM platform <StatusBadge status={data.platform.status === 'HEALTHY' ? 'AVAILABLE' : 'DEGRADED'} /></span>
      </div>
      {error && <div className="alert danger" role="alert">{error}</div>}
      <div className="department-grid">{headline.map(card)}</div>
      {others.length > 0 && (
        <div className="other-departments">
          <button className="link" onClick={() => setShowOthers(open => !open)} aria-expanded={showOthers}>
            {showOthers ? 'Hide' : 'Show'} {others.length} other department systems
          </button>
          {showOthers && <div className="department-grid">{others.map(card)}</div>}
        </div>
      )}
      <p className="muted small-text">Simulate outage is for test environments only.</p>
    </section>
  );
}
