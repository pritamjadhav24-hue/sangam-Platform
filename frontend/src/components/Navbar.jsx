import { useCallback, useState } from 'react';
import { languageText, translateNotification } from '../i18n';
import { useDismiss } from '../useDismiss';
import { Bell, BellOff, CheckCheck } from 'lucide-react';
import { formatNotificationTime, notificationIcon, notificationTone } from '../notificationFormat';

export default function Navbar({ page, setPage, citizen, language = 'en', onLanguageChange, onLogout, onNotificationSelect, onMarkAllRead, notifications }) {
  const [bellOpen, setBellOpen] = useState(false);
  const closeBell = useCallback(() => setBellOpen(false), []);
  const bellRef = useDismiss(bellOpen, closeBell);
  const role = citizen?.role;
  const t = languageText(language);
  const items = notifications || [];
  const unread = items.filter(item => !item.read).length;
  // Citizens get a single "Notifications" nav item (with an unread badge)
  // leading to the dedicated Notifications page -- no separate bell/popup.
  // Officer/Admin never got that dedicated page, so they keep their
  // original bell + dropdown popup, restored below, unchanged in behaviour.
  const links = role === 'CITIZEN'
    ? [['dashboard', t.homeNav], ['schemes', t.schemesNav], ['myApplications', t.myApplicationsNav], ['notificationsPage', t.notificationsNav, unread], ['profile', t.profileNav]]
    : role === 'OFFICER' ? [['officer', 'Officer Desk']]
    : role === 'ADMIN' ? [['adminDashboard', 'Overview'], ['adminApplications', 'Applications'], ['adminProviders', 'Providers'], ['adminActivity', 'Activity'], ['adminAnalytics', 'Analytics'], ['adminSchemes', 'Schemes'], ['adminAlerts', 'Incidents'], ['audit', 'Audit'], ['adminProfile', 'Profile']] : [];
  const adminActivePage = page === 'adminApplicationDetail' ? 'adminApplications'
    : page === 'adminProviderDetail' || page === 'health' ? 'adminProviders'
    : page === 'adminSchemeDetail' ? 'adminSchemes' : page;

  function selectBellNotification(notification) {
    setBellOpen(false);
    onNotificationSelect?.(notification);
  }

  return <>
    <div className="tricolor" aria-hidden="true" />
    <nav aria-label={language === 'en' ? 'Main navigation' : 'मुख्य नेव्हिगेशन'}>
      <button className="brand brand-button" onClick={() => citizen && setPage(role === 'CITIZEN' ? 'dashboard' : role === 'OFFICER' ? 'officer' : 'adminDashboard')} aria-label="SANGAM home">
        <img className="brand-logo" src="/brand/sangam-logo-240.webp" alt="" width="62" height="34" />
        <div><strong>SANGAM</strong><small>{language === 'en' ? 'Federated Government Interoperability Platform' : 'फेडरेटेड शासकीय इंटरऑपरेबिलिटी प्लॅटफॉर्म'}</small></div>
      </button>
      <div className="navlinks">
        {citizen && links.map(([key, label, badge]) => (
          <button key={key} className={adminActivePage === key ? 'active' : ''} aria-current={adminActivePage === key ? 'page' : undefined} onClick={() => setPage(key)}>
            {label}{badge > 0 && <span className="nav-notification-badge">{badge}</span>}
          </button>
        ))}
      </div>
      {citizen && (
        <div className="nav-tools">
          <button className="language-switch" onClick={() => onLanguageChange?.(language === 'en' ? 'mr' : 'en')} aria-label="Change language">{language === 'en' ? 'मराठी' : 'English'}</button>
          {(role === 'OFFICER' || role === 'ADMIN') && (
            <div className="notification-wrap" ref={bellRef}>
              <button className="notification-button" onClick={() => setBellOpen(open => !open)} aria-label={language === 'en' ? 'Notifications' : 'सूचना'}>
                <Bell size={18} aria-hidden="true" /> <span className="notification-label">{language === 'en' ? 'Notifications' : 'सूचना'}</span>
                {unread > 0 && <span className="notification-badge">{unread}</span>}
              </button>
              {bellOpen && (
                <div className="notification-panel">
                  <div className="notification-heading">
                    <div><b>{language === 'en' ? 'Notifications' : 'सूचना'}</b> <small>{unread ? (language === 'en' ? `${unread} unread` : `${unread} नवीन`) : (language === 'en' ? 'All caught up' : 'सर्व वाचले')}</small></div>
                    {unread > 0 && onMarkAllRead && (
                      <button className="link button-with-icon" onClick={onMarkAllRead}><CheckCheck size={15} aria-hidden="true" />{language === 'en' ? 'Mark all as read' : 'सर्व वाचले'}</button>
                    )}
                  </div>
                  {items.length === 0 ? (
                    <div className="notification-empty"><BellOff size={22} aria-hidden="true" />{language === 'en' ? 'No notifications yet.' : 'सध्या कोणत्याही सूचना नाहीत.'}</div>
                  ) : (
                    items.slice(0, 8).map(notification => {
                      const note = translateNotification(notification, language);
                      const Icon = notificationIcon(notification);
                      return (
                        <button className={`notification-item ${notification.read ? '' : 'unread'}`} key={notification.notificationId} onClick={() => selectBellNotification(notification)}>
                          <span className={`notification-icon small ${notificationTone(notification)}`} aria-hidden="true"><Icon size={16} /></span>
                          <span className="notification-item-body">
                            <b>{note.title}</b>
                            <span>{note.message}</span>
                            <small><time dateTime={notification.createdAt}>{formatNotificationTime(notification.createdAt, language)}</time></small>
                          </span>
                          {!notification.read && <span className="unread-dot" aria-label={language === 'en' ? 'Unread' : 'न वाचलेले'} />}
                        </button>
                      );
                    })
                  )}
                  <button className="link notification-view-all" onClick={() => { setBellOpen(false); setPage('notificationsPage'); }}>
                    {language === 'en' ? 'View all notifications' : 'सर्व सूचना पहा'}
                  </button>
                </div>
              )}
            </div>
          )}
          <div className="signed"><b>{citizen.name}</b><small>{role === 'CITIZEN' ? (language === 'en' ? 'Citizen' : 'नागरिक') : role === 'OFFICER' ? (language === 'en' ? 'Officer' : 'अधिकारी') : (language === 'en' ? 'Admin' : 'प्रशासक')} · {citizen.userId || citizen.citizenId}</small></div>
          {onLogout && <button className="logout" onClick={onLogout}>{t.signOut}</button>}
        </div>
      )}
      {!citizen && onLanguageChange && (
        <div className="nav-tools">
          <button className="language-switch" onClick={() => onLanguageChange(language === 'en' ? 'mr' : 'en')} aria-label="Change language">{language === 'en' ? 'मराठी' : 'English'}</button>
        </div>
      )}
    </nav>
  </>;
}
