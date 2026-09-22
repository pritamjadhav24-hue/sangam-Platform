import { languageText } from '../i18n';
import { NEEDS_ATTENTION_STATUSES, requirementStateClass, requirementStateLabel } from '../requirementState';

function greetingKey() {
  const hour = new Date().getHours();
  if (hour < 12) return 'goodMorning';
  if (hour < 17) return 'goodAfternoon';
  return 'goodEvening';
}

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

  return (
    <main className="container citizen-home">
      <section className="citizen-welcome">
        <div>
          <p className="eyebrow">{t[greetingKey()]}</p>
          <h1>{t[greetingKey()]}, {firstName(citizen?.name)}</h1>
          <p>{t.heroBlurb}</p>
        </div>
        <div className="welcome-mark">SANGAM<span>{language === 'en' ? 'Federated Government Interoperability Platform' : 'फेडरेटेड शासकीय इंटरऑपरेबिलिटी प्लॅटफॉर्म'}</span></div>
      </section>

      <section className="citizen-actions">
        <div className="search-service browse-cta">
          <label>{language === 'en' ? 'Explore schemes' : 'योजना शोधा'}</label>
          <p className="muted">{language === 'en' ? 'Search and filter every government scheme available through SANGAM.' : 'SANGAM द्वारे उपलब्ध सर्व शासकीय योजना शोधा व गाळा.'}</p>
          <button className="primary" onClick={() => navigate('schemes')}>{language === 'en' ? 'Browse all schemes' : 'सर्व योजना पहा'}</button>
        </div>
        <div className="track-box">
          <div><p className="eyebrow">{t.trackTitle}</p><label htmlFor="quick-track">{t.applicationId}</label></div>
          <div className="track-input">
            <input id="quick-track" placeholder="Application ID" onKeyDown={event => { if (event.key === 'Enter' && event.currentTarget.value) navigate('tracking', event.currentTarget.value); }} />
            <button className="primary" onClick={() => { const value = document.getElementById('quick-track')?.value; if (value) navigate('tracking', value); }}>{t.track}</button>
          </div>
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
                    <span className={`status ${application.status === 'SUBMITTED' ? 'found' : 'pending'}`}>{application.status === 'SUBMITTED' ? (language === 'en' ? 'Submitted' : 'सादर केले') : (language === 'en' ? 'In progress' : 'सुरू आहे')}</span>
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

      {actionItems.length > 0 && (
        <section className="services-section">
          <div className="section-heading">
            <div><h2>{t.actionRequiredSection}</h2><p className="muted">{t.actionRequiredBlurb}</p></div>
          </div>
          <div className="requirement-list">
            {actionItems.map(({ application, requirement }) => (
              <article className="card requirement-card" key={`${application.appId}-${requirement.requirementCode}`}>
                <div className="requirement-card-heading">
                  <span className={`requirement-icon requirement-icon-${requirementStateClass(requirement.status)}`} aria-hidden="true">!</span>
                  <div>
                    <h3>{requirement.displayLabel}</h3>
                    <p className="muted">{application.schemeName} · <span className={`status ${requirementStateClass(requirement.status)}`}>{requirementStateLabel(requirement.status, language)}</span></p>
                  </div>
                </div>
                <div className="requirement-actions">
                  <button className="outline" onClick={() => onOpenApplication?.(application)}>{language === 'en' ? 'Resolve' : 'निराकरण करा'}</button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {highlighted.length > 0 && (
        <section className="services-section">
          <div className="section-heading">
            <div><p className="eyebrow">{t.explore}</p><h2>{language === 'en' ? 'Explore Government Schemes' : 'शासकीय योजना पहा'}</h2></div>
            <button className="outline" onClick={() => navigate('schemes')}>{language === 'en' ? 'View all' : 'सर्व पहा'}</button>
          </div>
          <div className="scheme-grid">
            {highlighted.map(scheme => {
              const id = scheme.serviceId || scheme.schemeId;
              return (
                <article className="scheme-card card" key={id}>
                  <div className="scheme-card-heading">
                    {scheme.category && <span className="tag">{scheme.category}</span>}
                    {appliedSchemeIds.has(id) && <span className="tag applied-tag">{t.alreadyApplied}</span>}
                  </div>
                  <h3>{language === 'en' ? scheme.name : (scheme.nameMr || scheme.name)}</h3>
                  <p>{scheme.description}</p>
                  <div className="scheme-card-footer">
                    <small>{language === 'en' ? scheme.department : (scheme.departmentMr || scheme.department)}</small>
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
