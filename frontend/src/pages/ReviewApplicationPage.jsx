import { useEffect, useState } from 'react';
import { api } from '../api';
import { requirementStateClass, requirementStateLabel } from '../requirementState';

export default function ReviewApplicationPage({ schemeId, citizen, navigate, language = 'en' }) {
  const [application, setApplication] = useState(null);
  const [scheme, setScheme] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    if (!schemeId) {
      setLoading(false);
      setError(language === 'en' ? 'No scheme was selected.' : 'कोणतीही योजना निवडलेली नाही.');
      return undefined;
    }
    // The same idempotent resume call ApplicationFormPage uses -- this never
    // creates a second application, it just re-fetches the one already
    // opened for this scheme.
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

  async function handleSubmit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const updated = await api.submitApplication(application.appId);
      setApplication(updated);
      setConfirmOpen(false);
    } catch (err) {
      setSubmitError(err.message || (language === 'en'
        ? 'This application could not be submitted. Please make sure every required item is complete and try again.'
        : 'हा अर्ज सादर करता आला नाही. कृपया सर्व आवश्यक माहिती पूर्ण असल्याची खात्री करून पुन्हा प्रयत्न करा.'));
      setConfirmOpen(false);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <main className="container narrow"><p className="loading-state" role="status">{language === 'en' ? 'Opening review…' : 'पुनरावलोकन उघडत आहे…'}</p></main>;
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
  const isSubmitted = application.status === 'SUBMITTED';

  if (isSubmitted) {
    return (
      <main className="container narrow">
        <div className="alert success" role="status">
          <h2>{language === 'en' ? 'Application submitted' : 'अर्ज सादर झाला'}</h2>
          <ul className="compact">
            <li><span>{language === 'en' ? 'Application ID' : 'अर्ज क्रमांक'}</span><span><code>{application.appId}</code></span></li>
            <li><span>{language === 'en' ? 'Scheme' : 'योजना'}</span><span>{schemeName}</span></li>
            <li><span>{language === 'en' ? 'Status' : 'स्थिती'}</span><span>{language === 'en' ? 'Submitted' : 'सादर केले'}</span></li>
            {application.submittedAt && <li><span>{language === 'en' ? 'Submitted on' : 'सादर केल्याची तारीख'}</span><span>{new Date(application.submittedAt).toLocaleString()}</span></li>}
          </ul>
        </div>
        <button className="outline" onClick={() => navigate('dashboard')}>{language === 'en' ? 'Back to dashboard' : 'डॅशबोर्डवर परत जा'}</button>
      </main>
    );
  }

  return (
    <main className="container narrow">
      <div className="page-title">
        <div>
          <p className="eyebrow">{language === 'en' ? 'Review application' : 'अर्जाचे पुनरावलोकन'} · <code>{application.appId}</code></p>
          <h1>{schemeName}</h1>
        </div>
      </div>

      <section className="card form-section">
        <h2>{language === 'en' ? 'Scheme' : 'योजना'}</h2>
        <p className="muted">{scheme?.category}</p>
        {scheme?.description && <p>{scheme.description}</p>}
      </section>

      <section className="card form-section">
        <h2>{language === 'en' ? 'Personal details' : 'वैयक्तिक तपशील'}</h2>
        <ul className="compact">
          <li><span>{language === 'en' ? 'Name' : 'नाव'}</span><span>{citizen?.name}</span></li>
          <li><span>{language === 'en' ? 'Citizen ID' : 'नागरिक क्रमांक'}</span><span>{citizen?.citizenId}</span></li>
          {citizen?.dob && <li><span>{language === 'en' ? 'Date of birth' : 'जन्मतारीख'}</span><span>{citizen.dob}</span></li>}
          {citizen?.phone && <li><span>{language === 'en' ? 'Phone' : 'फोन'}</span><span>{citizen.phone}</span></li>}
        </ul>
      </section>

      <section className="card form-section">
        <h2>{language === 'en' ? 'Requirements' : 'आवश्यकता'}</h2>
        <ul className="compact">
          {(application.requirements || []).map(requirement => (
            <li key={requirement.requirementCode}>
              <span>{requirement.displayLabel}{requirement.mandatory === false && (language === 'en' ? ' (optional)' : ' (ऐच्छिक)')}</span>
              <span className={`status ${requirementStateClass(requirement.status)}`}>{requirementStateLabel(requirement.status, language)}</span>
            </li>
          ))}
        </ul>
      </section>

      {submitError && <div className="alert danger" role="alert">{submitError}</div>}

      {!application.readyForSubmission ? (
        <section className="card form-section scheme-detail-actions">
          <div>
            <h2>{language === 'en' ? 'Action required' : 'कृती आवश्यक'}</h2>
            <p className="muted">
              {language === 'en'
                ? 'The following items still need action before this application can be submitted:'
                : 'हा अर्ज सादर करण्यापूर्वी खालील गोष्टींवर कृती आवश्यक आहे:'}
            </p>
            <ul className="compact">
              {application.blockingRequirements.map(item => (
                <li key={item.requirementCode}>
                  <span>{item.displayLabel}</span>
                  <span className={`status ${requirementStateClass(item.status)}`}>{requirementStateLabel(item.status, language)}</span>
                </li>
              ))}
            </ul>
          </div>
          <button className="primary" onClick={() => navigate('applicationForm')}>{language === 'en' ? 'Back to form' : 'फॉर्मवर परत जा'}</button>
        </section>
      ) : (
        <section className="card form-section scheme-detail-actions">
          <div>
            <h2>{language === 'en' ? 'Ready to submit' : 'सादर करण्यास तयार'}</h2>
            <p className="muted">{language === 'en' ? 'All required information is complete.' : 'सर्व आवश्यक माहिती पूर्ण आहे.'}</p>
          </div>
          <div className="requirement-actions">
            <button className="outline" onClick={() => navigate('applicationForm')}>{language === 'en' ? 'Back to form' : 'फॉर्मवर परत जा'}</button>
            <button className="primary" disabled={submitting} onClick={() => setConfirmOpen(true)}>
              {language === 'en' ? 'Submit Application' : 'अर्ज सादर करा'}
            </button>
          </div>
        </section>
      )}

      {confirmOpen && (
        <div className="notice consent-prompt">
          <p>{language === 'en'
            ? 'Submit this application? You will not be able to change your answers afterwards.'
            : 'हा अर्ज सादर करायचा का? त्यानंतर आपण उत्तरे बदलू शकणार नाही.'}</p>
          <div className="actions">
            <button className="outline" disabled={submitting} onClick={() => setConfirmOpen(false)}>{language === 'en' ? 'Cancel' : 'रद्द करा'}</button>
            <button className="primary" disabled={submitting} onClick={handleSubmit}>
              {submitting ? (language === 'en' ? 'Submitting…' : 'सादर होत आहे…') : (language === 'en' ? 'Confirm & Submit' : 'निश्चित करा व सादर करा')}
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
