import { useEffect, useState } from 'react';
import { api, setAuthFailureHandler, setSessionToken } from './api';
import { initialLanguage, LANGUAGE_KEY, languageText } from './i18n';
import Navbar from './components/Navbar';
import LoginPage from './pages/LoginPage';
import CitizenDashboard from './pages/CitizenDashboard';
import SchemesPage from './pages/SchemesPage';
import SchemeDetailPage from './pages/SchemeDetailPage';
import ApplicationFormPage from './pages/ApplicationFormPage';
import PlaceholderPage from './pages/PlaceholderPage';
import ServiceDiscoveryPage from './pages/ServiceDiscoveryPage';
import ConsentModalPage from './pages/ConsentModalPage';
import DependencyResolutionPage from './pages/DependencyResolutionPage';
import ReviewSubmitPage from './pages/ReviewSubmitPage';
import TrackingPage from './pages/TrackingPage';
import OfficerDashboard from './pages/OfficerDashboard';
import AuditLineagePage from './pages/AuditLineagePage';
import IntegrationHealthPage from './pages/IntegrationHealthPage';
import SangamMark from './components/SangamMark';

export default function App() {
  const [user, setUser] = useState(null), [page, setPage] = useState('dashboard'), [schemes, setSchemes] = useState([]), [discovery, setDiscovery] = useState(null), [appId, setAppId] = useState(null), [schemeId, setSchemeId] = useState(null), [language, setLanguage] = useState(initialLanguage);
  useEffect(() => { setAuthFailureHandler(() => { setSessionToken(null); setUser(null); setAppId(null); setDiscovery(null); setPage('dashboard'); }); return () => setAuthFailureHandler(null); }, []);
  useEffect(() => { if (user?.role === 'CITIZEN') api.services().then(x => setSchemes(x.services || [])).catch(() => {}); }, [user]);
  function changeLanguage(next) { setLanguage(next); localStorage.setItem(LANGUAGE_KEY, next); }
  async function login(id, pw) { const result = await api.login(id, pw); setSessionToken(result.token); setUser(result.user); setPage(result.user.role === 'CITIZEN' ? 'dashboard' : result.user.role === 'OFFICER' ? 'officer' : 'health'); }
  async function discover(timeout = false) { const result = await api.discover(user.citizenId, timeout, schemeId); setDiscovery(result); if (result.schemeId) setSchemeId(result.schemeId); return result; }
  async function consent(allow) { const result = await api.consent(user.citizenId, allow, schemeId); if (result.appId) setAppId(result.appId); return result; }
  async function domicile(id = appId) { const result = await api.domicile(user.citizenId, id); if (result.appId) setAppId(result.appId); return result; }
  async function submit() { const result = await api.submit(user.citizenId, appId); setAppId(result.appId); return result; }
  const navigate = (nextPage, id) => { setPage(nextPage); if (id) setAppId(id); };
  function viewScheme(id) { setSchemeId(id); setPage('schemeDetail'); }
  function openApplicationForm(scheme) { const id = scheme?.serviceId || scheme?.schemeId || scheme; if (id) setSchemeId(id); setPage('applicationForm'); }
  function logout() { setSessionToken(null); setUser(null); setAppId(null); setDiscovery(null); setPage('dashboard'); }
  function onNotificationSelect(notification) { if (notification.applicationId && user.role === 'CITIZEN') { setAppId(notification.applicationId); setPage('tracking'); } else if (user.role === 'OFFICER') setPage('officer'); else if (user.role === 'ADMIN') setPage('health'); }
  if (!user) return <><Navbar page={page} setPage={setPage} language={language} onLanguageChange={changeLanguage} /><LoginPage onLogin={login} /></>;
  const props = { navigate, language };
  const t = languageText(language);
  const content = {
    dashboard: <CitizenDashboard schemes={schemes} discovery={discovery} onViewScheme={viewScheme} {...props} />,
    schemes: <SchemesPage onViewScheme={viewScheme} {...props} />,
    schemeDetail: <SchemeDetailPage schemeId={schemeId} onApply={openApplicationForm} {...props} />,
    applicationForm: <ApplicationFormPage schemeId={schemeId} citizen={user} {...props} />,
    myApplications: <PlaceholderPage eyebrow={t.myApplicationsNav} title={t.myApplicationsNav} message={language === 'en' ? 'A full list of your applications is coming in the next release. Use "Track application" from Home to check an existing application.' : 'आपल्या अर्जांची संपूर्ण यादी पुढील आवृत्तीत उपलब्ध होईल. सध्याचा अर्ज तपासण्यासाठी मुख्यपृष्ठावरील "अर्जाचा मागोवा" वापरा.'} />,
    notificationsPage: <PlaceholderPage eyebrow={t.notificationsNav} title={t.notificationsNav} message={language === 'en' ? 'Use the notification bell in the top navigation to see your latest updates. A dedicated notifications page is coming soon.' : 'आपले अलीकडील अद्यतने पाहण्यासाठी वरील सूचना घंटा वापरा. स्वतंत्र सूचना पान लवकरच उपलब्ध होईल.'} />,
    profile: <PlaceholderPage eyebrow={t.profileNav} title={t.profileNav} message={language === 'en' ? 'Profile management is coming in a future release of the SANGAM citizen portal.' : 'प्रोफाइल व्यवस्थापन SANGAM नागरिक पोर्टलच्या भविष्यातील आवृत्तीत उपलब्ध होईल.'} />,
    discovery: <ServiceDiscoveryPage discovery={discovery} onDiscover={discover} {...props} />,
    consent: <ConsentModalPage service={schemes.find(item => item.serviceId === schemeId || item.schemeId === schemeId)} onConsent={consent} {...props} />,
    dependency: <DependencyResolutionPage onDomicile={domicile} {...props} />,
    review: <ReviewSubmitPage discovery={discovery} onDiscover={discover} onSubmit={submit} {...props} />,
    tracking: <TrackingPage appId={appId} onTrack={api.track} onDomicile={domicile} {...props} />,
    officer: <OfficerDashboard onQueue={api.queue} onAction={api.action} />,
    health: <IntegrationHealthPage onHealth={api.integrationHealth} onReset={api.resetDemo} />,
    audit: <AuditLineagePage onAudit={api.audit} />,
  }[page] || null;
  return <><Navbar page={page} setPage={setPage} citizen={user} language={language} onLanguageChange={changeLanguage} onLogout={logout} onNotificationSelect={onNotificationSelect} />{content}<Footer /></>;
}

function Footer() { return <footer className="site-footer"><div className="footer-brand"><SangamMark size={30}/><div><b>SANGAM</b><span>Federated Government Interoperability Platform</span></div></div><div className="footer-links"><span>Accessibility</span><span>Privacy</span><span>Help</span><span>Terms</span></div><small>SIH 2026 Prototype · Connecting Government Services, Seamlessly.</small></footer>; }
