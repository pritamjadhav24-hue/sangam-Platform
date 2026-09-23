import { useState } from 'react';
import { languageText } from '../i18n';
import SangamMark from './SangamMark';

export default function Navbar({ page, setPage, citizen, language = 'en', onLanguageChange, onLogout, notifications, demoCitizens, onDemoSwitch }) {
  const [switching, setSwitching] = useState(false);
  const role = citizen?.role;
  const t = languageText(language);
  const unread = (notifications || []).filter(item => !item.read).length;
  const links = role === 'CITIZEN'
    ? [['dashboard', t.homeNav], ['schemes', t.schemesNav], ['myApplications', t.myApplicationsNav], ['notificationsPage', t.notificationsNav, unread], ['profile', t.profileNav]]
    : role === 'OFFICER' ? [['officer', 'Officer Desk']] : role === 'ADMIN' ? [['health', 'Integration Health'], ['audit', 'Audit Lineage']] : [];

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
          <div className="signed"><b>{citizen.name}</b><small>{role === 'CITIZEN' ? (language === 'en' ? 'Citizen' : 'नागरिक') : role === 'OFFICER' ? (language === 'en' ? 'Officer' : 'अधिकारी') : (language === 'en' ? 'Admin' : 'प्रशासक')} · {citizen.userId || citizen.citizenId}</small></div>
          {onLogout && <button className="logout" onClick={onLogout}>{t.signOut}</button>}
        </div>
      )}
    </nav>
  </>;
}
