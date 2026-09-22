import { useEffect, useState } from 'react';
import { api } from '../api';

const STATE_LABELS = {
  en: {
    NOT_PROVIDED: 'Not provided', PROCESSING: 'Processing', RETRIEVED: 'Retrieved', VALIDATED: 'Verified',
    WAITING: 'Waiting', ACTION_REQUIRED: 'Action required', REJECTED: 'Rejected', FAILED: 'Failed',
  },
  mr: {
    NOT_PROVIDED: 'दिलेले नाही', PROCESSING: 'प्रक्रिया सुरू', RETRIEVED: 'प्राप्त झाले', VALIDATED: 'पडताळणी झाली',
    WAITING: 'प्रतीक्षेत', ACTION_REQUIRED: 'कृती आवश्यक', REJECTED: 'नाकारले', FAILED: 'अयशस्वी',
  },
};

const STATE_CLASS = {
  NOT_PROVIDED: 'missing', PROCESSING: 'pending', RETRIEVED: 'found', VALIDATED: 'found',
  WAITING: 'pending', ACTION_REQUIRED: 'exception', REJECTED: 'exception', FAILED: 'exception',
};

function RequirementCard({ requirement, applicationId, language, onChange }) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(null); // 'auto-fill' | 'upload' | null
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const isDocumentLike = requirement.dataType === 'DOCUMENT' || requirement.dataType === 'CERTIFICATE';
  const stateLabels = STATE_LABELS[language] || STATE_LABELS.en;
  const label = stateLabels[requirement.status] || requirement.status;
  const statusClass = STATE_CLASS[requirement.status] || 'missing';

  // Auto-Fill never retrieves anything until the citizen explicitly accepts
  // this per-requirement consent prompt -- wording is deliberately generic
  // and never names a department, provider, API or document source.
  async function handleAutoFillDecision(decision) {
    setConsentOpen(false);
    setBusy('auto-fill');
    setError(null);
    setNotice(null);
    try {
      const updated = await api.autoFillRequirement(applicationId, requirement.requirementCode, decision);
      onChange(updated);
      if (decision === 'REJECT') {
        setNotice(language === 'en'
          ? 'Automatic retrieval was not allowed. You can provide this manually.'
          : 'स्वयंचलित पुनर्प्राप्तीला परवानगी नव्हती. आपण हे स्वतः देऊ शकता.');
      }
    } catch (err) {
      setError(err.message || (language === 'en' ? 'Auto-Fill could not be started.' : 'ऑटो-फिल सुरू करता आले नाही.'));
    } finally {
      setBusy(null);
    }
  }

  async function handleUploadSubmit(event) {
    event.preventDefault();
    setBusy('upload');
    setError(null);
    try {
      const updated = await api.uploadRequirement(applicationId, requirement.requirementCode, { title, contentType: 'text/plain', content });
      onChange(updated);
      setUploadOpen(false);
      setTitle('');
      setContent('');
    } catch (err) {
      setError(err.message || (language === 'en' ? 'Upload failed.' : 'अपलोड अयशस्वी झाले.'));
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="card requirement-card">
      <div className="requirement-card-heading">
        <div>
          <h3>{requirement.displayLabel}{requirement.mandatory === false && <small className="muted"> ({language === 'en' ? 'optional' : 'ऐच्छिक'})</small>}</h3>
          <p className="muted">{language === 'en' ? 'Status' : 'स्थिती'}: <span className={`status ${statusClass}`}>{label}</span></p>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}
      {notice && <div className="notice">{notice}</div>}

      {consentOpen && (
        <div className="notice consent-prompt">
          <p>{language === 'en'
            ? 'Allow SANGAM to retrieve and verify this information for your application?'
            : 'आपल्या अर्जासाठी ही माहिती पुनर्प्राप्त व पडताळण्याची SANGAM ला परवानगी द्यायची का?'}</p>
          <div className="actions">
            <button className="outline" onClick={() => handleAutoFillDecision('REJECT')}>{language === 'en' ? 'Reject' : 'नकार द्या'}</button>
            <button className="primary" onClick={() => handleAutoFillDecision('ACCEPT')}>{language === 'en' ? 'Accept' : 'स्वीकारा'}</button>
          </div>
        </div>
      )}

      <div className="requirement-actions">
        <button className="outline" disabled={busy !== null} onClick={() => setConsentOpen(true)}>
          {busy === 'auto-fill' ? (language === 'en' ? 'Processing…' : 'प्रक्रिया सुरू…') : (language === 'en' ? 'Auto-Fill' : 'ऑटो-फिल')}
        </button>
        {isDocumentLike && (
          <button className="outline" disabled={busy !== null} onClick={() => setUploadOpen(open => !open)}>
            {language === 'en' ? 'Upload Manually' : 'स्वतः अपलोड करा'}
          </button>
        )}
      </div>

      {isDocumentLike && uploadOpen && (
        <form className="upload-form" onSubmit={handleUploadSubmit}>
          <label htmlFor={`title-${requirement.requirementCode}`}>{language === 'en' ? 'Document title' : 'दस्तऐवजाचे शीर्षक'}</label>
          <input id={`title-${requirement.requirementCode}`} required value={title} onChange={event => setTitle(event.target.value)} placeholder={requirement.displayLabel} />
          <label htmlFor={`content-${requirement.requirementCode}`}>{language === 'en' ? 'Document details (demo upload)' : 'दस्तऐवज तपशील (नमुना अपलोड)'}</label>
          <textarea id={`content-${requirement.requirementCode}`} required rows={3} value={content} onChange={event => setContent(event.target.value)} placeholder={language === 'en' ? 'This is a synthetic/demo upload -- no real document is required in the prototype.' : 'हे एक नमुना अपलोड आहे -- प्रोटोटाइपमध्ये खऱ्या दस्तऐवजाची आवश्यकता नाही.'} />
          <div className="actions">
            <button type="button" className="outline" onClick={() => setUploadOpen(false)}>{language === 'en' ? 'Cancel' : 'रद्द करा'}</button>
            <button type="submit" className="primary" disabled={busy !== null}>{busy === 'upload' ? (language === 'en' ? 'Uploading…' : 'अपलोड होत आहे…') : (language === 'en' ? 'Submit' : 'सबमिट करा')}</button>
          </div>
        </form>
      )}
    </article>
  );
}

export default function ApplicationFormPage({ schemeId, citizen, navigate, language = 'en' }) {
  const [application, setApplication] = useState(null);
  const [scheme, setScheme] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setApplication(null);
    if (!schemeId) {
      setLoading(false);
      setError(language === 'en' ? 'No scheme was selected.' : 'कोणतीही योजना निवडलेली नाही.');
      return undefined;
    }
    Promise.all([api.applyToScheme(schemeId), api.service(schemeId)])
      .then(([applicationResult, schemeResult]) => {
        if (!active) return;
        setApplication(applicationResult);
        setScheme(schemeResult);
        setLoading(false);
      })
      .catch(err => {
        if (!active) return;
        setError(err.message || (language === 'en' ? 'Unable to open this application right now.' : 'हा अर्ज सध्या उघडता आला नाही.'));
        setLoading(false);
      });
    return () => { active = false; };
  }, [schemeId, language]);

  function updateRequirement(updatedApplication) {
    setApplication(updatedApplication);
  }

  if (loading) {
    return <main className="container narrow"><p className="loading-state" role="status">{language === 'en' ? 'Opening application…' : 'अर्ज उघडत आहे…'}</p></main>;
  }
  if (error || !application) {
    return (
      <main className="container narrow">
        <div className="alert danger" role="alert">{error || (language === 'en' ? 'Application could not be loaded.' : 'अर्ज लोड करता आला नाही.')}</div>
        <button className="outline" onClick={() => navigate('schemes')}>{language === 'en' ? 'Back to schemes' : 'योजनांकडे परत जा'}</button>
      </main>
    );
  }

  const schemeName = scheme ? (language === 'en' ? scheme.name : (scheme.nameMr || scheme.name)) : application.schemeName;

  return (
    <main className="container narrow application-form">
      <div className="page-title">
        <div>
          <p className="eyebrow">{language === 'en' ? 'Application' : 'अर्ज'} · <code>{application.appId}</code></p>
          <h1>{schemeName}</h1>
        </div>
      </div>

      <section className="card form-section">
        <h2>{language === 'en' ? '1. Personal details' : '१. वैयक्तिक तपशील'}</h2>
        <ul className="compact">
          <li><span>{language === 'en' ? 'Name' : 'नाव'}</span><span>{citizen?.name}</span></li>
          <li><span>{language === 'en' ? 'Citizen ID' : 'नागरिक क्रमांक'}</span><span>{citizen?.citizenId}</span></li>
          {citizen?.dob && <li><span>{language === 'en' ? 'Date of birth' : 'जन्मतारीख'}</span><span>{citizen.dob}</span></li>}
          {citizen?.phone && <li><span>{language === 'en' ? 'Phone' : 'फोन'}</span><span>{citizen.phone}</span></li>}
        </ul>
      </section>

      {scheme && (
        <section className="card form-section">
          <h2>{language === 'en' ? '2. Scheme information' : '२. योजना माहिती'}</h2>
          <p className="muted">{scheme.category}</p>
          <p>{scheme.description}</p>
        </section>
      )}

      <section className="form-section">
        <h2>{language === 'en' ? '3. Required documents & information' : '३. आवश्यक दस्तऐवज व माहिती'}</h2>
        <div className="requirement-list">
          {(application.requirements || []).map(requirement => (
            <RequirementCard
              key={requirement.requirementCode}
              requirement={requirement}
              applicationId={application.appId}
              language={language}
              onChange={updateRequirement}
            />
          ))}
        </div>
      </section>

      <section className="card form-section scheme-detail-actions">
        <div>
          <h2>{language === 'en' ? '4. Review & continue' : '४. पुनरावलोकन व पुढे जा'}</h2>
          <p className="muted">{language === 'en' ? 'Final review and submission will be available in a future release.' : 'अंतिम पुनरावलोकन व सादरीकरण भविष्यातील आवृत्तीत उपलब्ध होईल.'}</p>
        </div>
        <button className="outline" onClick={() => navigate('dashboard')}>{language === 'en' ? 'Save & continue later' : 'जतन करा व नंतर सुरू ठेवा'}</button>
      </section>
    </main>
  );
}
