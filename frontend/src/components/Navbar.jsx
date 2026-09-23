import { useCallback, useState } from 'react';
import { languageText, translateNotification } from '../i18n';
import { useDismiss } from '../useDismiss';
import SangamMark from './SangamMark';

export default function Navbar({ page, setPage, citizen, language = 'en', onLanguageChange, onLogout, onNotificationSelect, notifications, demoCitizens, onDemoSwitch }) {
  const [switching, setSwitching] = useState(false);
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
    : role === 'OFFICER' ? [['officer', 'Officer Desk']] : role === 'ADMIN' ? [['health', 'Integration Health'], ['audit', 'Audit Lineage']] : [];

  function selectBellNotification(notification) {
    setBellOpen(false);
    onNotificationSelect?.(notification);
  }

  async function handleDemoSwitch(event) {
    const citizenId = event.target.value;
    event.target.value = '';
    if (!citizenId || !onDemoSwitch) return;
    setSwitching(true);
    try { await onDemoSwitch(citizenId); } finally { setSwitching(false); }
  }

  return <>
    <header className="tricolor" />
    <nav>
      <button className="brand brand-button" onClick={() => citizen && setPage(role === 'CITIZEN' ? 'dashboard' : role === 'OFFICER' ? 'officer' : 'health')} aria-label="Sangam home">
        <SangamMark size={34} />
        <div><strong>SANGAM</strong><small>{language === 'en' ? 'Federated Government Interoperability Platform' : 'फेडरेटेड शासकीय इंटरऑपरेबिलिटी प्लॅटफॉर्म'}</small></div>
      </button>
      <div className="navlinks">
        {citizen && links.map(([key, label, badge]) => (
          <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}>
            {label}{badge > 0 && <span className="nav-notification-badge">{badge}</span>}
          </button>
        ))}
      </div>
      {citizen && (
        <div className="nav-tools">
          {role === 'CITIZEN' && demoCitizens?.length > 0 && (
            <label className="demo-switcher" title="Development/demo tool: switches the signed-in citizen to a different seeded synthetic identity.">
              <span className="demo-switcher-badge">DEMO</span>
              <select aria-label="Switch demo citizen" disabled={switching} defaultValue="" onChange={handleDemoSwitch}>
                <option value="" disabled>{switching ? (language === 'en' ? 'Switching…' : 'बदलत आहे…') : (language === 'en' ? 'Switch citizen' : 'नागरिक बदला')}</option>
                {demoCitizens.map(item => <option key={item.citizenId} value={item.citizenId} disabled={item.citizenId === citizen.citizenId}>{item.name}{item.persona ? ` · ${item.persona.replace(/_/g, ' ')}` : ''}</option>)}
              </select>
            </label>
          )}
          <button className="language-switch" onClick={() => onLanguageChange?.(language === 'en' ? 'mr' : 'en')} aria-label="Change language">{language === 'en' ? 'मराठी' : 'English'}</button>
          {(role === 'OFFICER' || role === 'ADMIN') && (
            <div className="notification-wrap" ref={bellRef}>
              <button className="notification-button" onClick={() => setBellOpen(open => !open)} aria-label={language === 'en' ? 'Notifications' : 'सूचना'}>
                ♧ <span className="notification-label">{language === 'en' ? 'Notifications' : 'सूचना'}</span>
                {unread > 0 && <span className="notification-badge">{unread}</span>}
              </button>
              {bellOpen && (
                <div className="notification-panel">
                  <div className="notification-heading">
                    {language === 'en' ? 'Notifications' : 'सूचना'} <small>{unread ? (language === 'en' ? `${unread} unread` : `${unread} नवीन`) : (language === 'en' ? 'All caught up' : 'सर्व वाचले')}</small>
                  </div>
                  {items.length === 0 ? (
                    <p className="muted">{language === 'en' ? 'No notifications yet.' : 'सध्या कोणत्याही सूचना नाहीत.'}</p>
                  ) : (
                    items.slice(0, 8).map(notification => {
                      const note = translateNotification(notification, language);
                      return (
                        <button className={`notification-item ${notification.read ? '' : 'unread'}`} key={notification.notificationId} onClick={() => selectBellNotification(notification)}>
                          <b>{note.title}</b>
                          <span>{note.message}</span>
                          <small>{new Date(notification.createdAt).toLocaleString(language === 'mr' ? 'mr-IN' : 'en-IN')}</small>
                        </button>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          )}
          <div className="signed"><b>{citizen.name}</b><small>{role === 'CITIZEN' ? (language === 'en' ? 'Citizen' : 'नागरिक') : role === 'OFFICER' ? (language === 'en' ? 'Officer' : 'अधिकारी') : (language === 'en' ? 'Admin' : 'प्रशासक')} · {citizen.userId || citizen.citizenId}</small></div>
          {onLogout && <button className="logout" onClick={onLogout}>{t.signOut}</button>}
        </div>
      )}
    </nav>
  </>;
}
