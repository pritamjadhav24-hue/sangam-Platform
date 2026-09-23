import { categoryLabel } from '../i18n';

// The scheme catalogue (fetched once in App.jsx) already carries every field
// a scheme's detail view needs, so this page looks the scheme up there
// instead of making its own per-scheme request on every visit.
export default function SchemeDetailPage({ schemeId, schemes, navigate, onApply, language = 'en' }) {
  const scheme = (schemes || []).find(item => item.serviceId === schemeId || item.schemeId === schemeId);

  if (!schemes || schemes.length === 0) {
    return <main className="container narrow"><p className="loading-state" role="status">{language === 'en' ? 'Loading scheme…' : 'योजना लोड होत आहे…'}</p></main>;
  }
  if (!schemeId || !scheme) {
    return (
      <main className="container narrow">
        <div className="alert danger" role="alert">{language === 'en' ? 'Scheme not found.' : 'योजना सापडली नाही.'}</div>
        <button className="outline" onClick={() => navigate('schemes')}>{language === 'en' ? 'Back to schemes' : 'योजनांकडे परत जा'}</button>
      </main>
    );
  }

  const name = language === 'en' ? scheme.name : (scheme.nameMr || scheme.name);
  const department = language === 'en' ? scheme.department : (scheme.departmentMr || scheme.department);
  const description = language === 'en' ? scheme.description : (scheme.descriptionMr || scheme.description);
  const benefits = language === 'en' ? scheme.benefits : (scheme.benefitsMr || scheme.benefits);
  const eligibility = language === 'en' ? scheme.eligibility : (scheme.eligibilityMr || scheme.eligibility);
  const applicationWindow = language === 'en' ? scheme.applicationWindow : (scheme.applicationWindowMr || scheme.applicationWindow);
  const available = scheme.enabled !== false;

  return (
    <main className="container narrow scheme-detail">
      <button className="outline back-link" onClick={() => navigate('schemes')}>&larr; {language === 'en' ? 'All schemes' : 'सर्व योजना'}</button>

      <div className="page-title">
        <div>
          <p className="eyebrow">{categoryLabel(scheme.category, language)}{scheme.synthetic ? ` · ${language === 'en' ? 'Demo scheme' : 'नमुना योजना'}` : ''}</p>
          <h1>{name}</h1>
          <p className="muted">{department}</p>
        </div>
      </div>

      <section className="card scheme-detail-section">
        <h2>{language === 'en' ? 'About this scheme' : 'योजनेबद्दल'}</h2>
        <p>{description}</p>
      </section>

      {benefits && (
        <section className="card scheme-detail-section">
          <h2>{language === 'en' ? 'Benefits' : 'लाभ'}</h2>
          <p>{benefits}</p>
        </section>
      )}

      {eligibility && (
        <section className="card scheme-detail-section">
          <h2>{language === 'en' ? 'Eligibility' : 'पात्रता'}</h2>
          <p>{eligibility}</p>
        </section>
      )}

      {Array.isArray(scheme.requirements) && scheme.requirements.length > 0 && (
        <section className="card scheme-detail-section">
          <h2>{language === 'en' ? 'What you will need' : 'आवश्यक बाबी'}</h2>
          <ul className="compact">
            {scheme.requirements.map(requirement => (
              <li key={requirement.code}>
                <span>{language === 'en' ? requirement.label : (requirement.labelMr || requirement.label)}</span>
                <span>{requirement.mandatory ? (language === 'en' ? 'Required' : 'आवश्यक') : (language === 'en' ? 'Optional' : 'ऐच्छिक')}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {applicationWindow && (
        <section className="card scheme-detail-section">
          <h2>{language === 'en' ? 'Important information' : 'महत्त्वाची माहिती'}</h2>
          <p>{applicationWindow}</p>
        </section>
      )}

      <div className="scheme-detail-actions">
        <span className={available ? 'available-label' : 'future-label'}>
          {available ? (language === 'en' ? 'Available in prototype' : 'प्रोटोटाइपमध्ये उपलब्ध') : (language === 'en' ? 'Coming soon' : 'लवकरच उपलब्ध')}
        </span>
        <button className="primary" disabled={!available} onClick={() => onApply(scheme)}>
          {language === 'en' ? 'Apply' : 'अर्ज करा'}
        </button>
      </div>
    </main>
  );
}
