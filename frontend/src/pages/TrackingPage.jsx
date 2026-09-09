import { useEffect, useMemo, useState } from 'react';
import LifecycleTracker from '../components/LifecycleTracker';

const labels = {
  requirement: { title: 'Requirements discovered', description: 'The interoperability layer found verified records across connected systems.' },
  CONSENT_GRANTED: { title: 'Consent granted', description: 'Purpose-bound access was authorized by the citizen.' },
  MISSING_PREREQUISITE_DETECTED: { title: 'Missing domicile detected', description: 'The scholarship workflow identified a missing prerequisite.' },
  DEPENDENCY_CREATED: { title: 'Dependency created', description: 'A Revenue Department provider was selected automatically.' },
  REVENUE_SERVICE_REQUESTED: { title: 'Revenue request', description: 'The Revenue Department domicile service was triggered.' },
  DOMICILE_ISSUED: { title: 'Domicile issued', description: 'The issued reference was returned to this same application.' },
  WORKFLOW_RESUMED: { title: 'Workflow resumed', description: 'The scholarship workflow continued after the dependency completed.' },
  APPLICATION_SUBMITTED: { title: 'Application submitted', description: 'The unified application was submitted for review.' },
  OFFICER_ACTION: { title: 'Officer action', description: 'An authorized officer recorded a workflow decision.' },
  COMPLETED: { title: 'Completed', description: 'The application journey is complete.' },
};

function orchestrationSteps(app) {
  const events = app.workflowEvents || [];
  const steps = [];
  const has = type => events.find(event => event.type === type);
  if (events.some(event => event.type.endsWith('_VERIFIED'))) steps.push({ key: 'requirements', ...labels.requirement });
  ['CONSENT_GRANTED', 'MISSING_PREREQUISITE_DETECTED', 'DEPENDENCY_CREATED', 'REVENUE_SERVICE_REQUESTED', 'DOMICILE_ISSUED', 'WORKFLOW_RESUMED', 'APPLICATION_SUBMITTED'].forEach(type => {
    const event = has(type);
    if (event) steps.push({ key: type, ...labels[type], event });
  });
  const officer = has('OFFICER_ACTION');
  if (officer) steps.push({ key: 'OFFICER_ACTION', ...labels.OFFICER_ACTION, event: officer });
  if (app.status === 'COMPLETED' || (app.statusHistory || []).some(item => item.status === 'COMPLETED')) steps.push({ key: 'COMPLETED', ...labels.COMPLETED });
  return steps;
}

export default function TrackingPage({ appId, onTrack, navigate }) {
  const [app, setApp] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { if (appId) onTrack(appId).then(setApp).catch(err => setError(err.message)); }, [appId, onTrack]);
  const steps = useMemo(() => app ? orchestrationSteps(app) : [], [app]);
  const mappings = app?.requirements?.flatMap(requirement => requirement.mappingEvidence || []) || [];
  const dependency = app?.dependencies?.[0];
  if (error) return <main className="container"><div className="alert danger">Unable to load the application journey: {error}</div></main>;
  if (!app) return <main className="container"><p>Loading application timeline…</p></main>;
  return <main className="container">
    <div className="page-title"><div><p className="eyebrow">Unified application tracking · live orchestration state</p><h1>{app.appId}</h1><p>Current status: <b>{app.status.replaceAll('_', ' ')}</b></p></div><button className="outline" onClick={() => navigate('officer')}>Open officer desk</button></div>
    <div className="notice"><b>One journey, connected departments:</b> the citizen does not need to manually visit the next department. Application correlation: <code>{app.appId}</code></div>
    <div className="card"><h2>Workflow / orchestration timeline</h2><p className="muted">These steps are built from the application’s recorded events and status history.</p><div className="workflow-list">{steps.map((step, index) => <div className="workflow-step" key={step.key}><i>{index + 1}</i><div><b>{step.title}</b><p>{step.description}</p>{step.event?.payload?.dependencyId && <small>Dependency {step.event.payload.dependencyId}</small>}{step.event?.payload?.recordId && <small>Reference {step.event.payload.recordId}</small>}</div></div>)}</div></div>
    <div className="grid two">
      <div className="card"><h2>Dependency orchestration</h2>{dependency ? <><div className="dependency-grid"><span>Missing requirement</span><b>Domicile Certificate</b><span>Provider</span><b>{dependency.provider}</b><span>Dependency ID</span><code>{dependency.dependencyId}</code><span>Status</span><strong className="good">{dependency.status}</strong><span>Result reference</span><code>{dependency.resultReference || 'Awaiting issuance'}</code></div></> : <p className="muted">No dependency has been created for this application.</p>}</div>
      <div className="card"><h2>Consent authorization</h2>{app.consent ? <div className="dependency-grid"><span>Decision</span><strong className={app.consent.decision === 'ALLOW' ? 'good' : 'warn'}>{app.consent.decision}</strong><span>Consumer</span><b>{app.consent.consumer}</b><span>Purpose</span><b>{app.consent.purpose}</b><span>Consent ID</span><code>{app.consent.consentId}</code><span>Allowed attributes</span><span>{app.consent.allowed?.join(', ') || 'None'}</span><span>Expires</span><span>{new Date(app.consent.expiresAt).toLocaleString()}</span></div> : <p className="muted">No consent receipt is linked to this journey.</p>}</div>
    </div>
    <div className="card"><h2>Interoperability summary</h2><div className="metric-row"><span><b>{new Set(app.requirements.map(item => item.source)).size}</b> source systems</span><span><b>{mappings.length}</b> deterministic mappings</span><span><b>{app.auditEntries?.length || 0}</b> correlated audit entries</span></div><p className="muted">Canonical mapping and provenance remain attached to each requirement. See the discovery screen for the full source-field → canonical-field evidence.</p>{mappings.length > 0 && <table><thead><tr><th>Source field</th><th>Canonical field</th><th>Source</th><th>Provenance</th></tr></thead><tbody>{mappings.slice(0, 8).map((mapping, index) => <tr key={`${mapping.sourceField}-${mapping.canonicalField}-${index}`}><td><code>{mapping.sourceField}</code></td><td><code>{mapping.canonicalField}</code></td><td>{mapping.sourceSystem}</td><td>{mapping.sourceRecordId || '—'}</td></tr>)}</tbody></table>}</div>
    <div className="card"><h2>Eligibility determination</h2><p>{app.eligibility.eligible ? 'Income and academic rules passed. The recorded journey is complete after authorized review.' : app.eligibility.reasons.join(' ')}</p></div>
  </main>;
}
