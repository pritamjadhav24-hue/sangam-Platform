import { Component, Suspense, lazy, useEffect, useRef, useState } from 'react';
import { api, setAuthFailureHandler, setSessionToken } from './api';
import { initialLanguage, LANGUAGE_KEY } from './i18n';
import Navbar from './components/Navbar';
import LoginPage from './pages/LoginPage';
import CitizenDashboard from './pages/CitizenDashboard';
import SchemesPage from './pages/SchemesPage';
import SchemeDetailPage from './pages/SchemeDetailPage';
import ApplicationFormPage from './pages/ApplicationFormPage';
import ReviewApplicationPage from './pages/ReviewApplicationPage';
import MyApplicationsPage from './pages/MyApplicationsPage';
import ProfilePage from './pages/ProfilePage';
import NotificationsPage from './pages/NotificationsPage';

// Officer and Admin screens are only ever used by staff roles, so they are
// split into their own chunks and never downloaded by a citizen's browser.
// Built by a function so "Try again" after a failed chunk download can make
// fresh lazy components: React.lazy remembers a failed import, and browsers
// cache a failed module URL, so a retry re-imports the chunk URL the browser
// reported with a cache-busting query (when the browser reports it).
function loadStaffPages(attempt = 0) {
  const load = factory => lazy(() => (attempt === 0 ? factory() : factory().catch(error => {
    const url = /(https?:\/\/[^\s'"]+?\.(?:m?js|jsx))(?:\?[^\s'"]*)?/.exec(error?.message || '')?.[1];
    if (!url || new URL(url).origin !== window.location.origin) throw error; // only ever our own chunks
    return import(/* @vite-ignore */ `${url}?retry=${attempt}`);
  })));
  return {
    OfficerDashboard: load(() => import('./pages/OfficerDashboard')),
    AuditLineagePage: load(() => import('./pages/AuditLineagePage')),
    AdminDashboardPage: load(() => import('./pages/admin/AdminDashboardPage')),
    AdminApplicationsPage: load(() => import('./pages/admin/AdminApplicationsPage')),
    AdminApplicationDetailPage: load(() => import('./pages/admin/AdminApplicationDetailPage')),
    AdminProvidersPage: load(() => import('./pages/admin/AdminProvidersPage')),
    AdminProviderDetailPage: load(() => import('./pages/admin/AdminProviderDetailPage')),
    AdminAlertsPage: load(() => import('./pages/admin/AdminAlertsPage')),
    AdminAnalyticsPage: load(() => import('./pages/admin/AdminAnalyticsPage')),
    AdminSchemesPage: load(() => import('./pages/admin/AdminSchemesPage')),
    AdminSchemeDetailPage: load(() => import('./pages/admin/AdminSchemeDetailPage')),
    AdminProfilePage: load(() => import('./pages/admin/AdminProfilePage')),
    AdminActivityPage: load(() => import('./pages/admin/AdminActivityPage')),
  };
}

// The session token is deliberately memory-only, so a browser refresh
// always requires signing in again. Only the non-sensitive admin view
// (page key + selected record ids) is remembered per tab, so an Admin who
// refreshes lands back where they were right after re-authenticating.
const ADMIN_ROUTE_KEY = 'sangam.adminRoute';
const ADMIN_PAGES = new Set(['adminDashboard', 'adminApplications', 'adminApplicationDetail', 'adminProviders', 'adminProviderDetail', 'adminActivity', 'adminAnalytics', 'adminSchemes', 'adminSchemeDetail', 'adminAlerts', 'audit', 'adminProfile', 'notificationsPage']);
function readAdminRoute() {
  try { return JSON.parse(sessionStorage.getItem(ADMIN_ROUTE_KEY) || 'null'); } catch { return null; }
}
function writeAdminRoute(route) {
  try { sessionStorage.setItem(ADMIN_ROUTE_KEY, JSON.stringify(route)); } catch { /* storage unavailable: route simply isn't restored */ }
}
const HOME_PAGE = { CITIZEN: 'dashboard', OFFICER: 'officer', ADMIN: 'adminDashboard' };

export default function App() {
  const [user, setUser] = useState(null), [page, setPage] = useState('dashboard'), [schemes, setSchemes] = useState([]), [appId, setAppId] = useState(null), [schemeId, setSchemeId] = useState(null), [language, setLanguage] = useState(initialLanguage);
  const [applications, setApplications] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const readIds = useRef(new Set());
  const [adminApplicationId, setAdminApplicationId] = useState(null);
  const [adminProviderId, setAdminProviderId] = useState(null);
  const [adminSchemeId, setAdminSchemeId] = useState(null);
  const [sessionNotice, setSessionNotice] = useState('');
  const [staffModules, setStaffModules] = useState(loadStaffPages);
  const [staffAttempt, setStaffAttempt] = useState(0);
  const signedIn = useRef(false);
  useEffect(() => { document.documentElement.lang = language === 'mr' ? 'mr' : 'en'; }, [language]);
  useEffect(() => {
    if (user?.role === 'ADMIN' && ADMIN_PAGES.has(page)) {
      writeAdminRoute({ page, applicationId: adminApplicationId, providerId: adminProviderId, schemeId: adminSchemeId });
    }
  }, [user, page, adminApplicationId, adminProviderId, adminSchemeId]);
  // A 401 while signed in means the session expired (or the account was
  // revoked): return to sign-in and say why. A 401 from a failed sign-in
  // attempt is handled by the login form itself.
  useEffect(() => {
    setAuthFailureHandler(() => {
      if (signedIn.current) setSessionNotice(language === 'mr' ? 'आपले सत्र संपले आहे. कृपया पुन्हा साइन इन करा.' : 'Your session has expired. Please sign in again.');
      signedIn.current = false;
      setSessionToken(null); setUser(null); setAppId(null); setPage('dashboard');
    });
    return () => setAuthFailureHandler(null);
  }, [language]);
  useEffect(() => {
    if (user?.role !== 'CITIZEN') return undefined;
    let active = true;
    api.services().then(x => { if (active) setSchemes(x.services || []); }).catch(() => {});
    return () => { active = false; };
  }, [user]);
  // Every persisted application for the signed-in citizen -- the single
  // source of truth the dashboard, scheme catalogue (applied-status badges)
  // and My Applications page all read from, re-fetched on every navigation
  // so it never goes stale after Auto-Fill/submit changes something. Guarded
  // against a slow request from a previous session resolving after a newer
  // one and overwriting it -- only the most recent effect run may apply.
  useEffect(() => {
    if (user?.role !== 'CITIZEN') return undefined;
    let active = true;
    api.applications().then(x => { if (active) setApplications(x.applications || []); }).catch(() => {});
    return () => { active = false; };
  }, [user, page]);
  // Notifications, lifted here (not fetched separately by the navbar badge
  // and the notifications page) so both always agree and the backend is
  // only ever asked once per navigation -- no interval polling.
  useEffect(() => {
    if (!user) { setNotifications([]); readIds.current = new Set(); return undefined; }
    let active = true;
    // Anything already read on this client stays read, even if a fetch that
    // started before the mark-as-read request finished returns it as unread.
    const fetchNotifications = () => api.notifications(user.role).then(x => {
      if (active) setNotifications((x.notifications || []).map(item => readIds.current.has(item.notificationId) ? { ...item, read: true } : item));
    }).catch(() => {});
    fetchNotifications();
    // Operators watching an outage need to see it without navigating; only
    // administrators get a light background refresh.
    const interval = user.role === 'ADMIN' ? setInterval(fetchNotifications, 20000) : null;
    return () => { active = false; if (interval) clearInterval(interval); };
  }, [user, page]);
  function changeLanguage(next) { setLanguage(next); try { localStorage.setItem(LANGUAGE_KEY, next); } catch { /* preference simply isn't remembered */ } }
  async function login(id, pw) {
    completeSignIn(await api.login(id, pw));
  }
  async function demoLogin(citizenId) {
    completeSignIn(await api.publicDemoSignIn(citizenId));
  }
  function completeSignIn(result) {
    signedIn.current = true;
    setSessionNotice('');
    setSessionToken(result.token); setUser(result.user); setApplications([]); setNotifications([]); setAppId(null); setSchemeId(null);
    if (result.user.role === 'ADMIN') {
      const saved = readAdminRoute();
      if (saved && ADMIN_PAGES.has(saved.page)) {
        setAdminApplicationId(saved.applicationId || null); setAdminProviderId(saved.providerId || null); setAdminSchemeId(saved.schemeId || null);
        setPage(saved.page);
        return;
      }
    }
    setPage(HOME_PAGE[result.user.role] || 'dashboard');
  }
  const navigate = (nextPage, id) => { setPage(nextPage); if (id) setAppId(id); };
  function viewScheme(id) { setSchemeId(id); setPage('schemeDetail'); }
  function openApplicationForm(scheme) { const id = scheme?.serviceId || scheme?.schemeId || scheme; if (id) setSchemeId(id); setPage('applicationForm'); }
  function openApplication(application) { if (application?.serviceId) setSchemeId(application.serviceId); setPage(application?.status === 'SUBMITTED' ? 'reviewApplication' : 'applicationForm'); }
  function logout() { signedIn.current = false; try { sessionStorage.removeItem(ADMIN_ROUTE_KEY); } catch { /* ignore */ } setSessionToken(null); setUser(null); setApplications([]); setNotifications([]); setAppId(null); setSchemeId(null); setPage('dashboard'); }
  async function markAllNotificationsRead() {
    notifications.forEach(item => readIds.current.add(item.notificationId));
    setNotifications(items => items.map(item => ({ ...item, read: true })));
    try { await api.markAllNotificationsRead(); } catch { /* the next refetch reconciles with the backend */ }
  }
  async function markNotificationRead(notification) {
    if (notification.read) return;
    readIds.current.add(notification.notificationId);
    setNotifications(items => items.map(item => item.notificationId === notification.notificationId ? { ...item, read: true } : item));
    try { await api.markNotificationRead(notification.notificationId); } catch { /* backend remains authoritative; next refetch will reconcile */ }
  }
  // "Visit": open whatever the notification is about (and mark it read).
  async function onNotificationSelect(notification) {
    markNotificationRead(notification);
    if (notification.applicationId && user.role === 'CITIZEN') {
      const application = applications.find(item => item.appId === notification.applicationId);
      if (application) { openApplication(application); return; }
      setAppId(notification.applicationId); setPage('myApplications');
    } else if (user.role === 'OFFICER') setPage('officer');
    else if (user.role === 'ADMIN') {
      // Operational notifications name what they are about.
      const target = notification.target || {};
      const applicationId = target.applicationId || notification.applicationId;
      if (target.kind === 'application' && applicationId) navigateAdmin('adminApplicationDetail', applicationId);
      else if (target.kind === 'incident') setPage('adminAlerts');
      else if (target.providerId) openProviderDetail(target.providerId);
      else if (applicationId) navigateAdmin('adminApplicationDetail', applicationId);
      else setPage('adminDashboard');
    }
  }
  function navigateAdmin(nextPage, applicationId) {
    if (applicationId) setAdminApplicationId(applicationId);
    setPage(nextPage);
  }
  function openProviderDetail(providerId) {
    setAdminProviderId(providerId);
    setPage('adminProviderDetail');
  }
  function openSchemeDetail(schemeId) {
    setAdminSchemeId(schemeId);
    setPage('adminSchemeDetail');
  }
  if (!user) return <><Navbar page={page} setPage={setPage} language={language} onLanguageChange={changeLanguage} /><LoginPage onLogin={login} onDemoLogin={demoLogin} loadDemoAccounts={api.publicDemoAccounts} language={language} notice={sessionNotice} /><Footer language={language} /></>;
  const props = { navigate, language, notifications, schemes };
  const isStaff = user.role === 'OFFICER' || user.role === 'ADMIN';
  const citizenPages = {
    dashboard: () => <CitizenDashboard applications={applications} citizen={user} onViewScheme={viewScheme} onOpenApplication={openApplication} {...props} />,
    schemes: () => <SchemesPage applications={applications} onViewScheme={viewScheme} {...props} />,
    schemeDetail: () => <SchemeDetailPage schemeId={schemeId} applications={applications} onApply={openApplicationForm} {...props} />,
    applicationForm: () => <ApplicationFormPage schemeId={schemeId} citizen={user} {...props} />,
    reviewApplication: () => <ReviewApplicationPage schemeId={schemeId} citizen={user} {...props} />,
    myApplications: () => <MyApplicationsPage applications={applications} onOpenApplication={openApplication} {...props} />,
    notificationsPage: () => <NotificationsPage onVisit={onNotificationSelect} onMarkRead={markNotificationRead} onMarkAllRead={markAllNotificationsRead} audience={user.role} {...props} />,
    profile: () => <ProfilePage citizen={user} applications={applications} loadProfile={api.citizenProfile} {...props} />,
  };
  const { OfficerDashboard, AuditLineagePage, AdminDashboardPage, AdminApplicationsPage, AdminApplicationDetailPage, AdminProvidersPage,
    AdminProviderDetailPage, AdminAlertsPage, AdminAnalyticsPage, AdminSchemesPage, AdminSchemeDetailPage, AdminProfilePage, AdminActivityPage } = staffModules;
  const staffPages = {
    officer: () => <OfficerDashboard onQueue={api.queue} onAction={api.action} />,
    adminDashboard: () => <AdminDashboardPage onNavigate={navigateAdmin} api={api} onReset={api.resetDemo} />,
    adminApplications: () => <AdminApplicationsPage onSelectApplication={id => navigateAdmin('adminApplicationDetail', id)} api={api} />,
    adminApplicationDetail: () => <AdminApplicationDetailPage applicationId={adminApplicationId} onBack={() => navigateAdmin('adminApplications')} api={api} />,
    adminProviders: () => <AdminProvidersPage onOpenProvider={openProviderDetail} api={api} />,
    adminProviderDetail: () => <AdminProviderDetailPage providerId={adminProviderId} onBack={() => navigateAdmin('adminProviders')} onNavigateToApplication={id => navigateAdmin('adminApplicationDetail', id)} api={api} />,
    adminAlerts: () => <AdminAlertsPage onNavigateToApplication={id => navigateAdmin('adminApplicationDetail', id)} api={api} />,
    adminAnalytics: () => <AdminAnalyticsPage api={api} onNavigate={navigateAdmin} onOpenProvider={openProviderDetail} onOpenApplication={id => navigateAdmin('adminApplicationDetail', id)} />,
    adminSchemes: () => <AdminSchemesPage api={api} onOpenScheme={openSchemeDetail} />,
    adminSchemeDetail: () => <AdminSchemeDetailPage api={api} schemeId={adminSchemeId} onBack={() => navigateAdmin('adminSchemes')} onOpenProvider={openProviderDetail} />,
    adminProfile: () => <AdminProfilePage api={api} language={language} />,
    adminActivity: () => <AdminActivityPage api={api} onOpenApplication={id => navigateAdmin('adminApplicationDetail', id)} />,
    health: () => <AdminProvidersPage onOpenProvider={openProviderDetail} api={api} />,
    audit: () => <AuditLineagePage onAudit={api.audit} />,
  };
  // Staff screens are only rendered for staff roles and citizen screens only
  // for citizens (the backend enforces the same split on every API call).
  const render = (isStaff ? staffPages : citizenPages)[page];
  const pageContent = render
    ? <Suspense fallback={<main className="container"><p className="loading-state" role="status">{language === 'mr' ? 'लोड होत आहे…' : 'Loading…'}</p></main>}>{render()}</Suspense>
    : <NotFound language={language} onHome={() => setPage(HOME_PAGE[user.role] || 'dashboard')} />;
  // Staff pages only: a failed chunk download (or render error) shows a
  // message with Try again instead of a blank screen. Citizen pages are
  // bundled with the app and render exactly as before.
  const retryStaffPages = () => { setStaffModules(loadStaffPages(staffAttempt + 1)); setStaffAttempt(staffAttempt + 1); };
  const content = isStaff && render
    ? <StaffPageBoundary key={`${staffAttempt}:${page}`} language={language} onRetry={retryStaffPages}>{pageContent}</StaffPageBoundary>
    : pageContent;
  return <><Navbar page={page} setPage={setPage} citizen={user} language={language} onLanguageChange={changeLanguage} onLogout={logout} onNotificationSelect={onNotificationSelect} onMarkAllRead={markAllNotificationsRead} notifications={notifications} />{content}<Footer language={language} /></>;
}

class StaffPageBoundary extends Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  // Deliberately no error details on screen (no stack traces or messages).
  componentDidCatch() {}
  render() {
    if (!this.state.failed) return this.props.children;
    const isMr = this.props.language === 'mr';
    return (
      <main className="container narrow">
        <section className="card empty-state" role="alert">
          <h1>{isMr ? 'हे पृष्ठ लोड करता आले नाही' : 'This page could not be loaded'}</h1>
          <p className="muted">{isMr
            ? 'कृपया आपले कनेक्शन तपासा व पुन्हा प्रयत्न करा. समस्या कायम राहिल्यास पृष्ठ रीलोड करा (आपल्याला पुन्हा साइन इन करावे लागेल).'
            : 'Please check your connection and try again. If the problem continues, reload the page (you will need to sign in again).'}</p>
          <div className="actions">
            <button className="outline" onClick={() => window.location.reload()}>{isMr ? 'पृष्ठ रीलोड करा' : 'Reload page'}</button>
            <button className="primary" onClick={this.props.onRetry}>{isMr ? 'पुन्हा प्रयत्न करा' : 'Try again'}</button>
          </div>
        </section>
      </main>
    );
  }
}

function NotFound({ language = 'en', onHome }) {
  const isMr = language === 'mr';
  return (
    <main className="container narrow">
      <section className="card empty-state" role="status">
        <h1>{isMr ? 'पृष्ठ सापडले नाही' : 'Page not found'}</h1>
        <p className="muted">{isMr ? 'आपण शोधत असलेले पृष्ठ उपलब्ध नाही किंवा आपल्याला ते पाहण्याची परवानगी नाही.' : 'The page you are looking for is not available, or you do not have access to it.'}</p>
        <button className="primary" onClick={onHome}>{isMr ? 'मुख्यपृष्ठावर जा' : 'Go to home'}</button>
      </section>
    </main>
  );
}

function Footer({ language = 'en' }) {
  const isMr = language === 'mr';
  return (
    <footer className="site-footer">
      <div className="footer-main">
        <div className="footer-brand">
          <span className="logo-badge small"><img src="/brand/sangam-logo-240.webp" alt="" width="54" height="30" loading="lazy" /></span>
          <div>
            <b>SANGAM</b>
            <span>{isMr ? 'फेडरेटेड शासकीय इंटरऑपरेबिलिटी प्लॅटफॉर्म' : 'Federated Government Interoperability Platform'}</span>
          </div>
        </div>
        <small>{isMr ? 'शासकीय सेवांचे अखंड, सुलभ एकत्रीकरण.' : 'Connecting government services, seamlessly.'}</small>
      </div>
    </footer>
  );
}
