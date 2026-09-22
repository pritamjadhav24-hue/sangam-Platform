import { useEffect, useMemo, useState } from 'react';

const labels = {
  en: {
    requirement: { title: 'Requirements discovered', description: 'The interoperability layer found verified records across connected systems.' },
    CONSENT_GRANTED: { title: 'Consent granted', description: 'Purpose-bound access was authorized by the citizen.' },
    MISSING_PREREQUISITE_DETECTED: { title: 'Missing domicile detected', description: 'The scholarship workflow identified a missing prerequisite.' },
    DEPENDENCY_CREATED: { title: 'Dependency created', description: 'A Revenue Department provider was selected automatically.' },
    PROVIDER_SELECTED: { title: 'Provider selected', description: 'The dependency registry selected a registered provider and adapter.' },
    REVENUE_SERVICE_REQUESTED: { title: 'Revenue request', description: 'The Revenue Department domicile service was triggered.' },
    DOMICILE_ISSUED: { title: 'Domicile issued', description: 'The issued reference was returned to this same application.' },
    WORKFLOW_RESUMED: { title: 'Workflow resumed', description: 'The scholarship workflow continued after the dependency completed.' },
    DEPENDENCY_SERVICE_FAILED: { title: 'Revenue service unavailable', description: 'The dependency remains linked and waiting; no completion was recorded.' },
    DEPENDENCY_RETRY_SCHEDULED: { title: 'Dependency retry recorded', description: 'The orchestrator retained the same dependency for a bounded retry.' },
    DEPENDENCY_RECOVERED: { title: 'Revenue service recovered', description: 'A later attempt completed the existing dependency.' },
    CONFLICT_DETECTED: { title: 'Conflict detected', description: 'Trusted source systems returned different values and the workflow paused for officer review.' },
    CONFLICT_RESOLVED: { title: 'Conflict resolved', description: 'An officer selected the authoritative source value for this application.' },
    APPLICATION_SUBMITTED: { title: 'Application submitted', description: 'The unified application was submitted for review.' },
    OFFICER_ACTION: { title: 'Officer action', description: 'An authorized officer recorded a workflow decision.' },
    COMPLETED: { title: 'Completed', description: 'The application journey is complete.' },
  },
  mr: {
    requirement: { title: 'आवश्यकता शोधल्या', description: 'इंटरऑपरेबिलिटी प्रणालीला जोडलेल्या यंत्रणांमधून पडताळलेले रेकॉर्ड सापडले.' },
    CONSENT_GRANTED: { title: 'संमती दिली', description: 'नागरिकाने उद्देश-मर्यादित प्रवेशासाठी अधिकृत परवानगी दिली.' },
    MISSING_PREREQUISITE_DETECTED: { title: 'अधिवास प्रमाणपत्र आवश्यक', description: 'शिष्यवृत्ती प्रक्रियेत आवश्यक अधिवास प्रमाणपत्राची कमतरता आढळली.' },
    DEPENDENCY_CREATED: { title: 'अवलंबित्व तयार केले', description: 'महसूल विभाग प्रदाता आपोआप निवडला गेला.' },
    PROVIDER_SELECTED: { title: 'प्रदाता निवडला', description: 'अवलंबित्व नोंदणीने अधिकृत प्रदाता व अडॅप्टर निवडला.' },
    REVENUE_SERVICE_REQUESTED: { title: 'महसूल सेवेस विनंती', description: 'महसूल विभागाची अधिवास सेवा सुरू करण्यात आली.' },
    DOMICILE_ISSUED: { title: 'अधिवास जारी केला', description: 'जारी केलेला संदर्भ क्रमांक याच अर्जास जोडण्यात आला.' },
    WORKFLOW_RESUMED: { title: 'कार्यप्रवाह पुन्हा सुरू', description: 'अवलंबित्व पूर्ण झाल्यावर अर्ज प्रक्रिया पुढे सुरू झाली.' },
    DEPENDENCY_SERVICE_FAILED: { title: 'महसूल सेवा अनुपलब्ध', description: 'अवलंबित्व जोडलेले राहिले आहे; अद्याप पूर्ण नोंद झालेली नाही.' },
    DEPENDENCY_RETRY_SCHEDULED: { title: 'पुन्हा प्रयत्न नोंदवला', description: 'ऑर्केस्ट्रेटरने मर्यादित प्रयत्नांसाठी अवलंबित्व कायम ठेवले.' },
    DEPENDENCY_RECOVERED: { title: 'महसूल सेवा पूर्ववत', description: 'पुढील प्रयत्नात विद्यमान अवलंबित्व पूर्ण झाले.' },
    CONFLICT_DETECTED: { title: 'माहितीत तफावत आढळली', description: 'विश्वासू प्रणालींनी भिन्न मूल्ये दिली, अधिकारी पुनरावलोकनासाठी प्रक्रिया थांबली.' },
    CONFLICT_RESOLVED: { title: 'तफावत सोडवली', description: 'अधिकृत अधिकाऱ्याने या अर्जासाठी अधिकृत माहिती निवडली.' },
    APPLICATION_SUBMITTED: { title: 'अर्ज सादर झाला', description: 'एकात्मिक अर्ज पुनरावलोकनासाठी सादर केला गेला.' },
    OFFICER_ACTION: { title: 'अधिकारी कृती', description: 'अधिकृत अधिकाऱ्याने कार्यप्रवाह निर्णय नोंदवला.' },
    COMPLETED: { title: 'पूर्ण झाले', description: 'अर्ज प्रक्रिया पूर्ण झाली आहे.' },
  },
};

function orchestrationSteps(app, language = 'en') {
  const events = app.workflowEvents || [];
  const steps = [];
  const dict = labels[language] || labels.en;
  const has = type => events.find(event => event.type === type);
  if (events.some(event => event.type.endsWith('_VERIFIED'))) steps.push({ key: 'requirements', ...dict.requirement });
  ['CONSENT_GRANTED', 'MISSING_PREREQUISITE_DETECTED', 'DEPENDENCY_CREATED', 'PROVIDER_SELECTED', 'REVENUE_SERVICE_REQUESTED', 'DEPENDENCY_SERVICE_FAILED', 'DEPENDENCY_RETRY_SCHEDULED', 'DEPENDENCY_RECOVERED', 'CONFLICT_DETECTED', 'CONFLICT_RESOLVED', 'DOMICILE_ISSUED', 'WORKFLOW_RESUMED', 'APPLICATION_SUBMITTED'].forEach(type => {
    events.filter(event => event.type === type).forEach((event, index) => steps.push({ key: `${type}-${index}`, ...dict[type], event }));
  });
  const officer = has('OFFICER_ACTION');
  if (officer) steps.push({ key: 'OFFICER_ACTION', ...dict.OFFICER_ACTION, event: officer });
  if (app.status === 'COMPLETED' || (app.statusHistory || []).some(item => item.status === 'COMPLETED')) steps.push({ key: 'COMPLETED', ...dict.COMPLETED });
  return steps;
}

export default function TrackingPage({ appId, onTrack, onDomicile, navigate, language = 'en' }) {
  const [app, setApp] = useState(null);
  const [error, setError] = useState('');
  const [retrying, setRetrying] = useState(false);
  const isMr = language === 'mr';
  useEffect(() => { if (appId) onTrack(appId).then(setApp).catch(err => setError(err.message)); }, [appId, onTrack]);
  const steps = useMemo(() => app ? orchestrationSteps(app, language) : [], [app, language]);
  const mappings = app?.requirements?.flatMap(requirement => requirement.mappingEvidence || []) || [];
  const dependency = app?.dependencies?.[0];
  async function retryDependency() {
    setRetrying(true);
    try { await onDomicile(app.appId); setApp(await onTrack(app.appId)); setError(''); } catch (err) { setError(err.message); } finally { setRetrying(false); }
  }
  if (error) return <main className="container"><div className="alert danger">{isMr ? 'अर्जाचा प्रवास लोड करता आला नाही: ' : 'Unable to load the application journey: '}{error}</div></main>;
  if (!app) return <main className="container"><p>{isMr ? 'अर्जाची टाइमलाइन लोड होत आहे…' : 'Loading application timeline…'}</p></main>;
  return <main className="container">
    <div className="page-title"><div><p className="eyebrow">{isMr ? 'एकात्मिक अर्ज मागोवा · थेट ऑर्केस्ट्रेशन स्थिती' : 'Unified application tracking · live orchestration state'}</p><h1>{app.appId}</h1><p>{isMr ? 'सध्याची स्थिती: ' : 'Current status: '}<b>{app.status.replaceAll('_', ' ')}</b></p></div><button className="outline" onClick={() => navigate('officer')}>{isMr ? 'अधिकारी डेस्क उघडा' : 'Open officer desk'}</button></div>
    <div className="notice"><b>{isMr ? 'एकच प्रवास, जोडलेले विभाग:' : 'One journey, connected departments:'}</b> {isMr ? 'नागरिकाला पुढील विभागाकडे प्रत्यक्ष जाण्याची आवश्यकता नाही.' : 'the citizen does not need to manually visit the next department.'} {isMr ? 'अर्ज संदर्भ:' : 'Application correlation:'} <code>{app.appId}</code></div>
    <div className="card"><h2>{isMr ? 'कार्यप्रवाह / ऑर्केस्ट्रेशन टाइमलाइन' : 'Workflow / orchestration timeline'}</h2><p className="muted">{isMr ? 'हे टप्पे अर्जाच्या नोंदवलेल्या घटनांवर आणि स्थिती इतिहासावर आधारित आहेत.' : 'These steps are built from the application’s recorded events and status history.'}</p><div className="workflow-list">{steps.map((step, index) => <div className="workflow-step" key={step.key}><i>{index + 1}</i><div><b>{step.title}</b><p>{step.description}</p>{step.event?.payload?.dependencyId && <small>{isMr ? 'अवलंबित्व ' : 'Dependency '}{step.event.payload.dependencyId}</small>}{step.event?.payload?.recordId && <small>{isMr ? 'संदर्भ ' : 'Reference '}{step.event.payload.recordId}</small>}</div></div>)}</div></div>
    {app.conflicts?.length > 0 && <div className="card"><h2>{isMr ? 'आंतर-प्रणाली तफावत' : 'Cross-system conflicts'}</h2>{app.conflicts.map(conflict => <div className="review-box conflict-box" key={`${conflict.canonicalField}-${conflict.detectedAt}`}><b>{conflict.status} · {conflict.canonicalField}</b>{conflict.sources.map(source => <small key={`${conflict.canonicalField}-${source.sourceSystem}`}>{source.sourceSystem}: {source.value} · {source.sourceRecordId}</small>)}<small>{conflict.selectedSource ? `${isMr ? 'अधिकृत निर्णय' : 'Resolved by'} ${conflict.selectedSource}: ${conflict.selectedValue}` : (isMr ? 'अधिकारी निर्णयाची प्रतीक्षा' : 'Awaiting officer resolution')}</small></div>)}</div>}
    <div className="grid two">
      <div className="card"><h2>{isMr ? 'अवलंबित्व ऑर्केस्ट्रेशन' : 'Dependency orchestration'}</h2>{dependency ? <><div className="dependency-grid"><span>{isMr ? 'अनुपलब्ध आवश्यकता' : 'Missing requirement'}</span><b>{dependency.requiredService}</b><span>{isMr ? 'निवडलेला प्रदाता' : 'Provider selected'}</span><b>{dependency.provider}</b><span>{isMr ? 'सेवा' : 'Service'}</span><b>{dependency.serviceName}</b><span>{isMr ? 'अडॅप्टर' : 'Adapter'}</span><span>{dependency.adapter}</span><span>{isMr ? 'निवडीचे कारण' : 'Selection reason'}</span><span>{dependency.providerSelection?.reason || (isMr ? 'नोंदणीकृत प्रदाता क्षमता' : 'Registered provider capability')}</span><span>{isMr ? 'प्रदाता स्थिती' : 'Provider health'}</span><strong className={dependency.providerStatus === 'AVAILABLE' ? 'good' : 'warn'}>{dependency.providerStatus || 'AVAILABLE'}</strong><span>{isMr ? 'अवलंबित्व आयडी' : 'Dependency ID'}</span><code>{dependency.dependencyId}</code><span>{isMr ? 'स्थिती' : 'Status'}</span><strong className={dependency.status === 'COMPLETED' ? 'good' : 'warn'}>{dependency.status}</strong><span>{isMr ? 'प्रयत्न' : 'Attempt'}</span><b>{dependency.attempts || 0}/{dependency.maxAttempts || 3}</b><span>{isMr ? 'निकाल संदर्भ' : 'Result reference'}</span><code>{dependency.resultReference || (isMr ? 'जारी होण्याची प्रतीक्षा' : 'Awaiting issuance')}</code></div>{dependency.lastError && <div className="alert danger">{dependency.lastError}</div>}{dependency.status !== 'COMPLETED' && <button className="primary" onClick={retryDependency} disabled={retrying}>{retrying ? (isMr ? 'पुन्हा प्रयत्न करत आहे…' : 'Retrying service…') : (isMr ? 'अवलंबित्व सेवेचा पुन्हा प्रयत्न करा' : 'Retry dependency service')}</button>}</> : <p className="muted">{isMr ? 'या अर्जासाठी कोणतेही अवलंबित्व तयार केलेले नाही.' : 'No dependency has been created for this application.'}</p>}</div>
      <div className="card"><h2>{isMr ? 'संमती प्रमाणीकरण' : 'Consent authorization'}</h2>{app.consent ? <div className="dependency-grid"><span>{isMr ? 'निर्णय' : 'Decision'}</span><strong className={app.consent.decision === 'ALLOW' ? 'good' : 'warn'}>{app.consent.decision}</strong><span>{isMr ? 'ग्राहक विभाग' : 'Consumer'}</span><b>{app.consent.consumer}</b><span>{isMr ? 'उद्देश' : 'Purpose'}</span><b>{app.consent.purpose}</b><span>{isMr ? 'संमती आयडी' : 'Consent ID'}</span><code>{app.consent.consentId}</code><span>{isMr ? 'अनुमत माहिती' : 'Allowed attributes'}</span><span>{app.consent.allowed?.join(', ') || (isMr ? 'काहीही नाही' : 'None')}</span><span>{isMr ? 'कालबाह्य तारीख' : 'Expires'}</span><span>{new Date(app.consent.expiresAt).toLocaleString(isMr ? 'mr-IN' : 'en-IN')}</span></div> : <p className="muted">{isMr ? 'या प्रवासाशी कोणतीही संमती पावती जोडलेली नाही.' : 'No consent receipt is linked to this journey.'}</p>}</div>
    </div>
    <div className="card"><h2>{isMr ? 'इंटरऑपरेबिलिटी सारांश' : 'Interoperability summary'}</h2><div className="metric-row"><span><b>{new Set(app.requirements.map(item => item.source)).size}</b> {isMr ? 'स्रोत प्रणाली' : 'source systems'}</span><span><b>{mappings.length}</b> {isMr ? 'निश्चित मॅपिंग' : 'deterministic mappings'}</span><span><b>{app.auditEntries?.length || 0}</b> {isMr ? 'संबंधित ऑडिट नोंदी' : 'correlated audit entries'}</span></div><p className="muted">{isMr ? 'कॅनोनिकल मॅपिंग आणि पुरावा प्रत्येक आवश्यकतेशी जोडलेला राहतो.' : 'Canonical mapping and provenance remain attached to each requirement. See the discovery screen for the full source-field → canonical-field evidence.'}</p>{mappings.length > 0 && <table><thead><tr><th>{isMr ? 'स्रोत फील्ड' : 'Source field'}</th><th>{isMr ? 'कॅनोनिकल फील्ड' : 'Canonical field'}</th><th>{isMr ? 'स्रोत' : 'Source'}</th><th>{isMr ? 'पुरावा' : 'Provenance'}</th></tr></thead><tbody>{mappings.slice(0, 8).map((mapping, index) => <tr key={`${mapping.sourceField}-${mapping.canonicalField}-${index}`}><td><code>{mapping.sourceField}</code></td><td><code>{mapping.canonicalField}</code></td><td>{mapping.sourceSystem}</td><td>{mapping.sourceRecordId || '—'}</td></tr>)}</tbody></table>}</div>
    <div className="card"><h2>{isMr ? 'पात्रता निर्धारण' : 'Eligibility determination'}</h2><p>{app.eligibility.eligible ? (isMr ? 'उत्पन्न आणि शैक्षणिक नियम पात्र ठरले. अधिकृत पुनरावलोकनानंतर नोंदवलेला प्रवास पूर्ण झाला आहे.' : 'Income and academic rules passed. The recorded journey is complete after authorized review.') : app.eligibility.reasons.join(' ')}</p></div>
  </main>;
}
