import { ArrowLeft, ArrowRight, Building2, CalendarDays, CircleCheck, FileText, ListChecks, ShieldCheck } from 'lucide-react';
import { categoryLabel } from '../i18n';
import { applicationStateLabel } from '../applicationState';
import { schemeImage } from '../schemeImages';

const STEPS = {
  en: ['Start your application', 'Allow Auto-Fill to fetch verified records from the departments', 'Upload anything that could not be verified', 'Review and submit', 'Track the status and notifications'],
  mr: ['अर्ज सुरू करा', 'विभागांकडील पडताळलेल्या नोंदी मिळवण्यासाठी ऑटो-फिलला परवानगी द्या', 'पडताळता न आलेल्या बाबी अपलोड करा', 'पुनरावलोकन करून सादर करा', 'स्थिती व सूचनांचा मागोवा घ्या'],
};

// The scheme catalogue (fetched once in App.jsx) already carries every field
// a scheme's detail view needs, so this page looks the scheme up there
// instead of making its own per-scheme request on every visit.
export default function SchemeDetailPage({ schemeId, schemes, applications, navigate, onApply, language = 'en' }) {
  const scheme = (schemes || []).find(item => item.serviceId === schemeId || item.schemeId === schemeId);
  const isMr = language === 'mr';

  if (!schemes || schemes.length === 0) {
    return <main className="container narrow"><p className="loading-state" role="status">{isMr ? 'योजना लोड होत आहे…' : 'Loading scheme…'}</p></main>;
  }
  if (!schemeId || !scheme) {
    return (
      <main className="container narrow">
        <div className="alert danger" role="alert">{isMr ? 'योजना सापडली नाही.' : 'Scheme not found.'}</div>
        <button className="outline" onClick={() => navigate('schemes')}>{isMr ? 'योजनांकडे परत जा' : 'Back to schemes'}</button>
      </main>
    );
  }

  const pick = (en, mr) => (isMr ? (mr || en) : en);
  const name = pick(scheme.name, scheme.nameMr);
  const department = pick(scheme.department, scheme.departmentMr);
  const description = pick(scheme.description, scheme.descriptionMr);
  const benefits = pick(scheme.benefits, scheme.benefitsMr);
  const eligibility = pick(scheme.eligibility, scheme.eligibilityMr);
  const applicationWindow = pick(scheme.applicationWindow, scheme.applicationWindowMr);
  const available = scheme.enabled !== false;
  const image = schemeImage(scheme, language);
  const id = scheme.serviceId || scheme.schemeId;
  const existing = (applications || []).find(item => item.serviceId === id);
  const criteria = Array.isArray(scheme.eligibilityCriteria) ? scheme.eligibilityCriteria : [];
  const requirements = Array.isArray(scheme.requirements) ? scheme.requirements : [];

  return (
    <main className="container scheme-detail">
      <button className="link back-link button-with-icon" onClick={() => navigate('schemes')}><ArrowLeft size={16} aria-hidden="true" />{isMr ? 'सर्व योजना' : 'All schemes'}</button>

      <header className="scheme-hero">
        <img src={image.src} alt={image.alt} width="720" height="405" />
        <div className="scheme-hero-text">
          <span className="tag">{categoryLabel(scheme.category, language)}</span>
          <h1>{name}</h1>
          <p className="scheme-hero-department"><Building2 size={16} aria-hidden="true" />{isMr ? `${department} द्वारे उपलब्ध` : `Offered by ${department}`}</p>
        </div>
      </header>

      <div className="scheme-layout">
        <div className="scheme-main">
          <section className="card scheme-detail-section">
            <h2>{isMr ? 'योजनेबद्दल' : 'About this scheme'}</h2>
            <p>{description}</p>
            {benefits && (<><h3>{isMr ? 'लाभ' : 'Benefits'}</h3><p>{benefits}</p></>)}
          </section>

          {(eligibility || criteria.length > 0) && (
            <section className="card scheme-detail-section">
              <h2>{isMr ? 'पात्रता' : 'Eligibility'}</h2>
              {eligibility && <p>{eligibility}</p>}
              {criteria.length > 0 && (
                <>
                  <p className="muted">{isMr ? 'आपली माहिती पडताळली जात असताना या निकषांनुसार आपली पात्रता तपासली जाते:' : 'Your eligibility is checked against these criteria as your information is verified:'}</p>
                  <ul className="check-list eligibility-criteria-list">
                    {criteria.map(item => <li key={item.id}><CircleCheck size={18} aria-hidden="true" />{pick(item.label, item.labelMr)}</li>)}
                  </ul>
                </>
              )}
            </section>
          )}

          {requirements.length > 0 && (
            <section className="card scheme-detail-section">
              <h2>{isMr ? 'आवश्यक माहिती व दस्तऐवज' : 'Required information and documents'}</h2>
              <ul className="document-list">
                {requirements.map(requirement => (
                  <li key={requirement.code}>
                    <FileText size={18} aria-hidden="true" />
                    <span>{pick(requirement.label, requirement.labelMr)}</span>
                    <span className={`status ${requirement.mandatory ? 'required' : 'optional'}`}>{requirement.mandatory ? (isMr ? 'आवश्यक' : 'Required') : (isMr ? 'ऐच्छिक' : 'Optional')}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="card scheme-detail-section">
            <h2>{isMr ? 'अर्ज कसा करावा' : 'How to apply'}</h2>
            <ol className="step-list">
              {STEPS[isMr ? 'mr' : 'en'].map(step => <li key={step}>{step}</li>)}
            </ol>
          </section>
        </div>

        <aside className="scheme-aside">
          <div className="card apply-panel">
            <p className={`availability ${available ? 'on' : 'off'}`}>{available ? <CircleCheck size={18} aria-hidden="true" /> : <CalendarDays size={18} aria-hidden="true" />}
              {available ? (isMr ? 'ऑनलाइन उपलब्ध' : 'Available online') : (isMr ? 'लवकरच उपलब्ध' : 'Coming soon')}</p>
            {existing && <p className="muted">{isMr ? 'आपल्या अर्जाची स्थिती' : 'Your application'}: <b>{applicationStateLabel(existing.status, language)}</b></p>}
            <button className="primary button-with-icon wide" disabled={!available} onClick={() => onApply(scheme)}>
              {existing ? (isMr ? 'अर्ज उघडा' : 'Open application') : (isMr ? 'अर्ज करा' : 'Apply')}<ArrowRight size={18} aria-hidden="true" />
            </button>
            <ul className="aside-points">
              <li><ShieldCheck size={16} aria-hidden="true" />{isMr ? 'आपल्या संमतीनेच विभागांकडून पडताळणी' : 'Verified with departments only with your consent'}</li>
              <li><ListChecks size={16} aria-hidden="true" />{isMr ? `${requirements.length} आवश्यक बाबी` : `${requirements.length} items to provide`}</li>
            </ul>
            {applicationWindow && <p className="muted small-text"><CalendarDays size={14} aria-hidden="true" /> {applicationWindow}</p>}
          </div>
        </aside>
      </div>
    </main>
  );
}
