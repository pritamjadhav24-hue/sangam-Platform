import { useEffect, useState } from 'react';
import { api, setSessionToken } from './api';
import { initialLanguage, LANGUAGE_KEY } from './i18n';
import Navbar from './components/Navbar';
import LoginPage from './pages/LoginPage';
import CitizenDashboard from './pages/CitizenDashboard';
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
  const [user, setUser] = useState(null), [page, setPage] = useState('dashboard'), [schemes, setSchemes] = useState([]), [discovery, setDiscovery] = useState(null), [appId, setAppId] = useState(null), [language, setLanguage] = useState(initialLanguage);
  useEffect(() => { if (user?.role === 'CITIZEN') api.schemes().then(x => setSchemes(x.schemes)).catch(() => {}); }, [user]);
  function changeLanguage(next) { setLanguage(next); localStorage.setItem(LANGUAGE_KEY, next); }
  async function login(id, pw) { const result = await api.login(id, pw); setSessionToken(result.token); setUser(result.user); setPage(result.user.role === 'CITIZEN' ? 'dashboard' : result.user.role === 'OFFICER' ? 'officer' : 'health'); }
  async function discover(timeout = false) { const result = await api.discover(user.citizenId, timeout); setDiscovery(result); return result; }
  async function consent(allow) { const result = await api.consent(user.citizenId, allow); if (result.appId) setAppId(result.appId); return result; }
  async function domicile(id = appId) { const result = await api.domicile(user.citizenId, id); if (result.appId) setAppId(result.appId); return result; }
  async function submit() { const result = await api.submit(user.citizenId, appId); setAppId(result.appId); return result; }
  const navigate = (nextPage, id) => { setPage(nextPage); if (id) setAppId(id); };
  function logout() { setSessionToken(null); setUser(null); setAppId(null); setDiscovery(null); setPage('dashboard'); }
  function onNotificationSelect(notification) { if (notification.applicationId && user.role === 'CITIZEN') { setAppId(notification.applicationId); setPage('tracking'); } else if (user.role === 'OFFICER') setPage('officer'); else if (user.role === 'ADMIN') setPage('health'); }
  if (!user) return <><Navbar page={page} setPage={setPage} language={language} onLanguageChange={changeLanguage} /><LoginPage onLogin={login} /></>;
  const props = { navigate, language };
  const content = { dashboard: <CitizenDashboard schemes={schemes} discovery={discovery} {...props} />, discovery: <ServiceDiscoveryPage discovery={discovery} onDiscover={discover} {...props} />, consent: <ConsentModalPage onConsent={consent} {...props} />, dependency: <DependencyResolutionPage onDomicile={domicile} {...props} />, review: <ReviewSubmitPage discovery={discovery} onDiscover={discover} onSubmit={submit} {...props} />, tracking: <TrackingPage appId={appId} onTrack={api.track} onDomicile={domicile} {...props} />, officer: <OfficerDashboard onQueue={api.queue} onAction={api.action} />, health: <IntegrationHealthPage onHealth={api.integrationHealth} onReset={api.resetDemo} />, audit: <AuditLineagePage onAudit={api.audit} /> }[page] || null;
  return <><Navbar page={page} setPage={setPage} citizen={user} language={language} onLanguageChange={changeLanguage} onLogout={logout} onNotificationSelect={onNotificationSelect} />{content}<Footer /></>;
}

function Footer() { return <footer className="site-footer"><div className="footer-brand"><SangamMark size={30}/><div><b>SANGAM</b><span>Federated Government Interoperability Platform</span></div></div><div className="footer-links"><span>Accessibility</span><span>Privacy</span><span>Help</span><span>Terms</span></div><small>SIH 2026 Prototype · Connecting Government Services, Seamlessly.</small></footer>; }
