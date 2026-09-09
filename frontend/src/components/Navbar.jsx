import { useEffect, useState } from 'react';
import { api } from '../api';

export default function Navbar({ page, setPage, citizen, onNotificationSelect }) {
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
  return <><header className="tricolor"/><nav><div className="brand"><span className="emblem">⚖</span><div>GovOrchestrator <small>महाराष्ट्र शासन · Federated Services</small></div></div><div className="navlinks">{citizen && links.map(([key, label]) => <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}>{label}</button>)}</div>{citizen && <div className="notification-wrap"><button className="notification-button" onClick={() => setOpen(!open)} aria-label="Notifications">Notifications {unread > 0 && <span className="notification-badge">{unread}</span>}</button>{open && <div className="notification-panel">{notifications.length === 0 ? <p className="muted">No notifications yet.</p> : notifications.slice(0, 8).map(notification => <button className={`notification-item ${notification.read ? '' : 'unread'}`} key={notification.notificationId} onClick={() => selectNotification(notification)}><b>{notification.title}</b><span>{notification.message}</span><small>{new Date(notification.createdAt).toLocaleString()}</small></button>)}</div>}</div>}{citizen && <div className="signed">Signed in: {citizen.name}<br/><small>{role} · {citizen.userId || citizen.citizenId}</small></div>}</nav></>
}
