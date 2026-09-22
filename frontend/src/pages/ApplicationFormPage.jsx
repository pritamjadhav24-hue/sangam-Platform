import { useEffect, useState } from 'react';
import { api } from '../api';
import { NEEDS_ATTENTION_STATUSES, requirementStateClass, requirementStateIcon, requirementStateLabel } from '../requirementState';

function RequirementCard({ requirement, applicationId, language, onChange, locked }) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(null); // 'auto-fill' | 'upload' | 'download' | null
  const [error, setError] = useState(null);
  const [viewedDocument, setViewedDocument] = useState(null);

  const isDocumentLike = requirement.dataType === 'DOCUMENT' || requirement.dataType === 'CERTIFICATE';
  const hasViewableDocument = isDocumentLike && requirement.status === 'VALIDATED';
  const label = requirementStateLabel(requirement.status, language);
  const statusClass = requirementStateClass(requirement.status);
  const needsAttention = NEEDS_ATTENTION_STATUSES.has(requirement.status);
  const isRetry = needsAttention; // same action, different button copy

  async function handleViewDocument() {
    setBusy('view');
    setError(null);
    try {
      const doc = await api.viewDocument(applicationId, requirement.requirementCode);
      setViewedDocument(doc);
    } catch (err) {
      setError(err.message || (language === 'en' ? 'The document could not be opened.' : 'दस्तऐवज उघडता आले नाही.'));
    } finally {
      setBusy(null);
    }
  }

  async function handleDownloadDocument() {
    setBusy('download');
    setError(null);
    try {
      const { blob, filename } = await api.downloadDocument(applicationId, requirement.requirementCode);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || (language === 'en' ? 'The document could not be downloaded.' : 'दस्तऐवज डाउनलोड करता आले नाही.'));
    } finally {
      setBusy(null);
    }
  }

  // Auto-Fill never retrieves anything until the citizen explicitly accepts
  // this per-requirement consent prompt -- wording is deliberately generic
  // and never names a department, provider, API or document source. A
  // retry goes through this exact same consent-gated call -- consent is
  // never skipped just because a prior attempt already happened.
  async function handleAutoFillDecision(decision) {
    setConsentOpen(false);
    setBusy('auto-fill');
    setError(null);
    try {
      const updated = await api.autoFillRequirement(applicationId, requirement.requirementCode, decision);
      onChange(updated);
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
        <span className={`requirement-icon requirement-icon-${statusClass}`} aria-hidden="true">{requirementStateIcon(requirement.status)}</span>
        <div>
          <h3>{language === 'en' ? requirement.displayLabel : (requirement.displayLabelMr || requirement.displayLabel)}{requirement.mandatory === false && <small className="muted"> ({language === 'en' ? 'optional' : 'ऐच्छिक'})</small>}</h3>
          <p className="muted">{language === 'en' ? 'Status' : 'स्थिती'}: <span className={`status ${statusClass}`}>{label}</span></p>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}
      {/* Backend-persisted guidance, not local-only state -- this survives a
          page refresh/reopen because it is derived from requirement.userAction
          (part of the API response), not from something set only right after
          a button click. */}
      {needsAttention && requirement.userAction && <div className="notice">{requirement.userAction}</div>}

      {consentOpen && !locked && (
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

      {locked ? (
        <p className="muted">{language === 'en' ? 'This application has been submitted and can no longer be changed.' : 'हा अर्ज सादर करण्यात आला आहे आणि तो आता बदलता येणार नाही.'}</p>
      ) : (
        <div className="requirement-actions">
          <button className="outline" disabled={busy !== null} onClick={() => setConsentOpen(true)}>
            {busy === 'auto-fill'
              ? (language === 'en' ? 'Processing…' : 'प्रक्रिया सुरू…')
              : isRetry
                ? (language === 'en' ? 'Retry' : 'पुन्हा प्रयत्न करा')
                : (language === 'en' ? 'Auto-Fill' : 'ऑटो-फिल')}
          </button>
          {isDocumentLike && (
            <button className="outline" disabled={busy !== null} onClick={() => setUploadOpen(open => !open)}>
              {language === 'en' ? 'Upload Manually' : 'स्वतः अपलोड करा'}
            </button>
          )}
        </div>
      )}

      {hasViewableDocument && (
        <div className="requirement-actions">
          <button className="outline" disabled={busy !== null} onClick={handleViewDocument}>
            {busy === 'view' ? (language === 'en' ? 'Opening…' : 'उघडत आहे…') : (language === 'en' ? 'View Document' : 'दस्तऐवज पहा')}
          </button>
          <button className="outline" disabled={busy !== null} onClick={handleDownloadDocument}>
            {busy === 'download' ? (language === 'en' ? 'Downloading…' : 'डाउनलोड होत आहे…') : (language === 'en' ? 'Download' : 'डाउनलोड करा')}
          </button>
        </div>
      )}

      {viewedDocument && (
        <div className="notice document-preview">
          <div className="document-preview-heading">
            <b>{viewedDocument.title}</b>
            <button className="link" onClick={() => setViewedDocument(null)}>{language === 'en' ? 'Close' : 'बंद करा'}</button>
          </div>
          <pre>{viewedDocument.content}</pre>
        </div>
      )}

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

      {application.status === 'SUBMITTED' && (
        <div className="alert success" role="status">
          {language === 'en' ? 'This application has already been submitted.' : 'हा अर्ज आधीच सादर करण्यात आला आहे.'}
        </div>
      )}

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
              locked={application.status === 'SUBMITTED'}
            />
          ))}
        </div>
      </section>

      <section className="card form-section scheme-detail-actions">
        <div>
          <h2>{language === 'en' ? '4. Review & continue' : '४. पुनरावलोकन व पुढे जा'}</h2>
          <p className="muted">{language === 'en' ? 'Review your application before submitting it.' : 'सादर करण्यापूर्वी आपल्या अर्जाचे पुनरावलोकन करा.'}</p>
        </div>
        <div className="requirement-actions">
          <button className="outline" onClick={() => navigate('dashboard')}>{language === 'en' ? 'Save & continue later' : 'जतन करा व नंतर सुरू ठेवा'}</button>
          <button className="primary" onClick={() => navigate('reviewApplication')}>{language === 'en' ? 'Continue to Review' : 'पुनरावलोकनाकडे जा'}</button>
        </div>
      </section>
    </main>
  );
}
