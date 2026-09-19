import { languageText } from '../i18n';

export default function ConsentModalPage({ onConsent, navigate, service, language = 'en' }) {
  const mr = language === 'mr';
  async function decide(allow) { await onConsent(allow); if (allow) navigate('dependency'); else navigate('dashboard'); }
  const t = languageText(language);
  const requirements = service?.requirements || [];
  return <main className="container narrow"><div className="card consent"><p className="eyebrow">{mr ? 'आपली परवानगी' : 'Your permission'}</p><h1>{mr ? 'आपली माहिती वापरण्याची परवानगी द्याल का?' : 'Allow us to use your information?'}</h1><p><b>{mr ? 'विभाग:' : 'Department:'}</b> {service?.department || 'Configured government service'}</p><p><b>{mr ? 'कारण:' : 'Purpose:'}</b> {service?.name || 'Configured service application'}</p><hr/><div className="consent-columns"><div><h3>{mr ? 'वापरली जाणारी माहिती' : 'Information requested by this service'}</h3><ul>{requirements.map(item => <li key={item.code}>{item.label || item.code.replaceAll('_', ' ')}</li>)}</ul></div><div><h3>{mr ? 'वापरली जाणार नाही' : 'Privacy safeguards'}</h3><ul className="excluded"><li>{mr ? 'अनावश्यक माहिती' : 'Unrequested attributes'}</li><li>{mr ? 'बायोमेट्रिक माहिती' : 'Biometric information'}</li></ul></div></div><p className="muted">{mr ? 'ही परवानगी सुरक्षित आहे आणि २४ तासांसाठी वैध आहे.' : 'This permission is purpose-bound, attribute-specific and valid for 24 hours.'}</p><div className="actions"><button className="outline danger-text" onClick={() => decide(false)}>{mr ? 'नकार द्या' : 'Deny and stop'}</button><button className="primary" onClick={() => decide(true)}>{mr ? 'परवानगी द्या' : 'Allow and continue'}</button></div></div></main>;
}
