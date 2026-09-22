import { languageText } from '../i18n';

export default function CitizenDashboard({ schemes, discovery, navigate, onViewScheme, language = 'en' }) {
  const t = languageText(language);
  const available = (schemes || []).filter(service => service.enabled !== false);
  const highlighted = available.slice(0, 3);
  const implemented = schemes?.[0];

  return (
    <main className="container citizen-home">
      <section className="citizen-welcome">
        <div>
          <p className="eyebrow">{language === 'en' ? 'Your services' : 'आपल्या सेवा'}</p>
          <h1>{t.welcome}</h1>
          <p>{t.welcomeCopy}</p>
        </div>
        <div className="welcome-mark">SANGAM<span>Federated service platform</span></div>
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

      <section className="current-application card">
        <div>
          <p className="eyebrow">{t.current}</p>
          <h2>{implemented?.name || (language === 'en' ? 'No service selected' : 'कोणतीही सेवा निवडलेली नाही')}</h2>
          <p>{discovery ? t.plainPrivacy : (language === 'en' ? 'Choose a scheme from the catalogue to begin.' : 'सुरू करण्यासाठी सूचीतून योजना निवडा.')}</p>
        </div>
        <div className="application-state">
          <span className="status found">{discovery ? (language === 'en' ? 'Information checked' : 'माहिती तपासली') : (language === 'en' ? 'Not started' : 'सुरू केलेले नाही')}</span>
          {discovery && <button className="outline" onClick={() => navigate('tracking')}>{t.track}</button>}
        </div>
      </section>

      {highlighted.length > 0 && (
        <section className="services-section">
          <div className="section-heading">
            <div><p className="eyebrow">{t.explore}</p><h2>{language === 'en' ? 'Recently added schemes' : 'नव्याने जोडलेल्या योजना'}</h2></div>
            <button className="outline" onClick={() => navigate('schemes')}>{language === 'en' ? 'View all' : 'सर्व पहा'}</button>
          </div>
          <div className="scheme-grid">
            {highlighted.map(scheme => {
              const id = scheme.serviceId || scheme.schemeId;
              return (
                <article className="scheme-card card" key={id}>
                  <div className="scheme-card-heading">{scheme.category && <span className="tag">{scheme.category}</span>}</div>
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
