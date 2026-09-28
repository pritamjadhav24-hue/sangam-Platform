import { useState } from 'react';
import { languageText, categoryLabel } from '../i18n';
import { NEEDS_ATTENTION_STATUSES } from '../requirementState';
import { applicationStateClass, applicationStateLabel } from '../applicationState';
import { schemeImage } from '../schemeImages';

function firstName(fullName) {
  return (fullName || '').split(' ')[0] || fullName;
}

export default function CitizenDashboard({ schemes, applications, citizen, navigate, onViewScheme, onOpenApplication, language = 'en' }) {
  const t = languageText(language);
  const available = (schemes || []).filter(service => service.enabled !== false);
  const highlighted = available.slice(0, 3);
  const apps = applications || [];

  const active = apps.filter(item => item.status === 'IN_PROGRESS');
  const submitted = apps.filter(item => item.status === 'SUBMITTED');
  const appliedSchemeIds = new Set(apps.map(item => item.serviceId));

  // "Action required" is derived entirely from persisted requirement state
  // (never invented): a requirement that was actually attempted and came
  // back needing the citizen's attention, not simply "not started yet".
  const actionItems = [];
  for (const application of apps) {
    for (const requirement of application.requirements || []) {
      if (NEEDS_ATTENTION_STATUSES.has(requirement.status)) {
        actionItems.push({ application, requirement });
      }
    }
  }

  const [trackError, setTrackError] = useState('');
  function trackApplication(rawValue) {
    const value = (rawValue || '').trim();
    if (!value) return;
    const application = apps.find(item => item.appId === value);
    if (application) { setTrackError(''); onOpenApplication?.(application); return; }
    setTrackError(language === 'en' ? 'No application found with this ID.' : 'या क्रमांकाचा कोणताही अर्ज सापडला नाही.');
  }

  return (
    <main className="container citizen-home">
      <section className="citizen-welcome">
        <div>
          <h1>{language === 'en' ? `Welcome, ${firstName(citizen?.name)}` : `स्वागत आहे, ${firstName(citizen?.name)}`}</h1>
          <p>{t.heroBlurb}</p>
        </div>
      </section>

      <section className="citizen-actions">
        <div className="card action-card">
          <p className="eyebrow">{language === 'en' ? 'Services' : 'सेवा'}</p>
          <h2>{language === 'en' ? 'Find a service' : 'सेवा शोधा'}</h2>
          <p className="muted">{language === 'en' ? 'Browse services from connected departments.' : 'जोडलेल्या विभागांच्या सेवा पहा.'}</p>
          <button className="primary" onClick={() => navigate('schemes')}>{language === 'en' ? 'Browse all schemes' : 'सर्व योजना पहा'}</button>
        </div>
        <div className="card action-card">
          <p className="eyebrow">{language === 'en' ? 'Applications' : 'अर्ज'}</p>
          <h2>{t.trackTitle}</h2>
          <label htmlFor="quick-track">{t.applicationId}</label>
          <div className="track-input">
            <input id="quick-track" placeholder={t.applicationId} onKeyDown={event => { if (event.key === 'Enter') trackApplication(event.currentTarget.value); }} />
            <button className="primary" onClick={() => trackApplication(document.getElementById('quick-track')?.value)}>{t.track}</button>
          </div>
          {trackError && <p className="muted" role="alert">{trackError}</p>}
        </div>
      </section>

      <section className="summary-grid" aria-label={language === 'en' ? 'Application overview' : 'अर्ज सारांश'}>
        <div className="summary-card blue">
          <span>{t.activeApplications}</span>
          <b>{active.length}</b>
        </div>
        <div className="summary-card">
          <span>{t.submittedApplications}</span>
          <b>{submitted.length}</b>
        </div>
        <div className={`summary-card${actionItems.length > 0 ? ' amber' : ''}`}>
          <span>{t.needsAttention}</span>
          <b>{actionItems.length}</b>
        </div>
      </section>

      <section className="services-section">
        <div className="section-heading">
          <div><h2>{t.yourApplications}</h2></div>
          {apps.length > 0 && <button className="outline" onClick={() => navigate('myApplications')}>{language === 'en' ? 'View all' : 'सर्व पहा'}</button>}
        </div>
        {apps.length === 0 ? (
          <div className="empty-state card">
            <span aria-hidden="true">◇</span>
            <h3>{t.noApplicationsTitle}</h3>
            <p className="muted">{t.noApplicationsBody}</p>
            <button className="primary" onClick={() => navigate('schemes')}>{language === 'en' ? 'Browse all schemes' : 'सर्व योजना पहा'}</button>
          </div>
        ) : (
          <div className="scheme-grid">
            {apps.slice(0, 4).map(application => {
              const total = (application.requirements || []).length;
              const satisfied = (application.requirements || []).filter(item => item.status === 'VALIDATED' || item.status === 'RETRIEVED').length;
              return (
                <article className="scheme-card card application-card" key={application.appId}>
                  <div className="scheme-card-heading">
                    <span className={`status ${applicationStateClass(application.status)}`}>{applicationStateLabel(application.status, language)}</span>
                  </div>
                  <h3>{application.schemeName || application.serviceId}</h3>
                  <p className="muted">{total > 0 ? `${satisfied}/${total} ${language === 'en' ? 'requirements verified' : 'आवश्यकता पडताळल्या'}` : ''}</p>
                  <div className="scheme-card-footer">
                    <small><code>{application.appId}</code></small>
                    <button className="outline" onClick={() => onOpenApplication?.(application)}>{t.viewApplication}</button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {highlighted.length > 0 && (
        <section className="services-section">
          <div className="section-heading">
            <div><p className="eyebrow">{t.explore}</p><h2>{language === 'en' ? 'Explore Government Schemes' : 'शासकीय योजना पहा'}</h2></div>
            <button className="outline" onClick={() => navigate('schemes')}>{language === 'en' ? 'View all' : 'सर्व पहा'}</button>
          </div>
          <div className="scheme-grid">
            {highlighted.map(scheme => {
              const id = scheme.serviceId || scheme.schemeId;
              const image = schemeImage(scheme, language);
              return (
                <article className="scheme-card card with-image" key={id}>
                  <img className="scheme-card-image" src={image.src} alt={image.alt} loading="lazy" width="720" height="405" />
                  <div className="scheme-card-heading">
                    {scheme.category && <span className="tag">{categoryLabel(scheme.category, language)}</span>}
                    {appliedSchemeIds.has(id) && <span className="tag applied-tag">{t.alreadyApplied}</span>}
                  </div>
                  <h3>{language === 'en' ? scheme.name : (scheme.nameMr || scheme.name)}</h3>
                  <p>{language === 'en' ? scheme.description : (scheme.descriptionMr || scheme.description)}</p>
                  <div className="scheme-card-footer">
                    <small>{language === 'en' ? `Offered by ${scheme.department}` : `${scheme.departmentMr || scheme.department} द्वारे उपलब्ध`}</small>
                    <button className="outline" onClick={() => onViewScheme(id)}>{language === 'en' ? 'View details' : 'तपशील पहा'}</button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}
    </main>
  );
}
