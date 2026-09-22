import { languageText } from '../i18n';
import { applicationStateClass, applicationStateLabel } from '../applicationState';

export default function MyApplicationsPage({ applications, onOpenApplication, navigate, language = 'en' }) {
  const t = languageText(language);
  const apps = applications || [];

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">{t.myApplicationsNav}</p>
          <h1>{t.yourApplications}</h1>
        </div>
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
          {apps.map(application => {
            const total = (application.requirements || []).length;
            const satisfied = (application.requirements || []).filter(item => item.status === 'VALIDATED' || item.status === 'RETRIEVED').length;
            return (
              <article className="scheme-card card application-card" key={application.appId}>
                <div className="scheme-card-heading">
                  <span className={`status ${applicationStateClass(application.status)}`}>{applicationStateLabel(application.status, language)}</span>
                </div>
                <h3>{application.schemeName || application.serviceId}</h3>
                <p className="muted">{total > 0 ? `${satisfied}/${total} ${language === 'en' ? 'requirements verified' : 'आवश्यकता पडताळल्या'}` : ''}</p>
                {application.submittedAt && <p className="muted">{language === 'en' ? 'Submitted on' : 'सादर केल्याची तारीख'}: {new Date(application.submittedAt).toLocaleDateString()}</p>}
                <div className="scheme-card-footer">
                  <small><code>{application.appId}</code></small>
                  <button className="outline" onClick={() => onOpenApplication?.(application)}>{t.viewApplication}</button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </main>
  );
}
