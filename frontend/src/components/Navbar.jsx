import { useEffect, useState } from 'react';
import { api } from '../api';

export default function Navbar({ page, setPage, citizen, onLogout, onNotificationSelect }) {
  const [notifications, setNotifications] = useState([]);
  const [open, setOpen] = useState(false);
  const role = citizen?.role;
  const links = role === 'CITIZEN' ? [['dashboard', 'Citizen Services']] : role === 'OFFICER' ? [['officer', 'Officer Desk']] : role === 'ADMIN' ? [['health', 'Integration Health'], ['audit', 'Audit Lineage']] : [];
  useEffect(() => {
    if (!citizen?.role) { setNotifications([]); return undefined; }
    let active = true;
    const load = () => api.notifications(citizen.role).then(result => { if (active) setNotifications(result.notifications || []); }).catch(() => {});
    load();
    const timer = setInterval(load, 4000);
    return () => { active = false; clearInterval(timer); };
  }, [citizen?.role, citizen?.userId]);
  async function selectNotification(notification) {
    try { await api.markNotificationRead(notification.notificationId); setNotifications(items => items.map(item => item.notificationId === notification.notificationId ? { ...item, read: true } : item)); } catch { /* backend remains authoritative */ }
    setOpen(false);
    if (onNotificationSelect) onNotificationSelect(notification);
  }
  const unread = notifications.filter(item => !item.read).length;
  return <><header className="tricolor"/><nav><button className="brand brand-button" onClick={() => citizen && setPage(citizen.role === 'CITIZEN' ? 'dashboard' : citizen.role === 'OFFICER' ? 'officer' : 'health')} aria-label="Sangam home"><span className="emblem">सं</span><div><strong>SANGAM</strong><small>Federated Government Interoperability Platform</small></div></button><div className="navlinks">{citizen && links.map(([key, label]) => <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}>{label}</button>)}</div>{citizen && <div className="nav-tools"><span className="language">मराठी <b>·</b> English</span><div className="notification-wrap"><button className="notification-button" onClick={() => setOpen(!open)} aria-label="Notifications">♧ <span className="notification-label">Notifications</span>{unread > 0 && <span className="notification-badge">{unread}</span>}</button>{open && <div className="notification-panel"><div className="notification-heading">Notifications <small>{unread ? `${unread} unread` : 'All caught up'}</small></div>{notifications.length === 0 ? <p className="muted">No notifications yet.</p> : notifications.slice(0, 8).map(notification => <button className={`notification-item ${notification.read ? '' : 'unread'}`} key={notification.notificationId} onClick={() => selectNotification(notification)}><b>{notification.title}</b><span>{notification.message}</span><small>{new Date(notification.createdAt).toLocaleString()}</small></button>)}</div>}</div><div className="signed"><b>{citizen.name}</b><small>{role} · {citizen.userId || citizen.citizenId}</small></div>{onLogout && <button className="logout" onClick={onLogout}>Sign out</button>}</div>}</nav></>
}
