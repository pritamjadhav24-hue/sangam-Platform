import { ArrowRight, BellOff, CheckCheck } from 'lucide-react';
import { languageText, translateNotification } from '../i18n';
import { formatNotificationTime, notificationIcon, notificationTone } from '../notificationFormat';

// Where an operational notification leads.
const TARGET_LABEL = { incident: 'Open incident', provider: 'Open provider', application: 'View application' };

function visitLabel(notification, isMr) {
  const kind = notification.target?.kind;
  if (kind && TARGET_LABEL[kind]) return TARGET_LABEL[kind];
  if (notification.target?.providerId) return TARGET_LABEL.provider;
  return isMr ? 'अर्ज पहा' : 'View application';
}

export default function NotificationsPage({ notifications, onVisit, onMarkRead, onMarkAllRead, language = 'en', audience = 'CITIZEN' }) {
  const t = languageText(language);
  const isMr = language === 'mr';
  const items = notifications || [];
  const unread = items.filter(item => !item.read);

  return (
    <main className="container narrow">
      <div className="page-title">
        <div>
          <p className="eyebrow">{isMr ? 'अद्यतने' : 'Updates'}</p>
          <h1>{t.notificationsNav}</h1>
          <p className="muted">{unread.length
            ? (isMr ? `${unread.length} न वाचलेल्या सूचना` : `${unread.length} unread`)
            : (isMr ? 'सर्व सूचना वाचल्या आहेत' : 'All notifications read')}</p>
        </div>
        {unread.length > 0 && (
          <button className="outline button-with-icon" onClick={() => (onMarkAllRead ? onMarkAllRead() : unread.forEach(item => onMarkRead?.(item)))}>
            <CheckCheck size={18} aria-hidden="true" />{isMr ? 'सर्व वाचले म्हणून चिन्हांकित करा' : 'Mark all as read'}
          </button>
        )}
      </div>

      {items.length === 0 ? (
        <div className="empty-state card">
          <BellOff size={30} aria-hidden="true" />
          <h3>{isMr ? 'आपण सर्व माहिती पाहिली आहे' : "You're all caught up"}</h3>
          <p className="muted">{audience === 'ADMIN'
            ? 'Provider outages and recoveries, fallback use, blocked applications and integration errors will appear here.'
            : (isMr ? 'आपल्या अर्ज व दस्तऐवजांबद्दलची नवीन माहिती येथे दिसेल.' : 'Updates about your applications and documents will appear here.')}</p>
        </div>
      ) : (
        <ul className="notification-list" aria-label={t.notificationsNav}>
          {items.map(notification => {
            const note = translateNotification(notification, language);
            const Icon = notificationIcon(notification);
            return (
              <li key={notification.notificationId} className={`card notification-card${notification.read ? '' : ' unread'}${notification.severity ? ` severity-${notification.severity.toLowerCase()}` : ''}`}>
                <span className={`notification-icon ${notificationTone(notification)}`} aria-hidden="true"><Icon size={20} /></span>
                <div className="notification-body">
                  <div className="notification-title-row">
                    <b>{note.title}</b>
                    {!notification.read && <span className="status new">{isMr ? 'नवीन' : 'New'}</span>}
                  </div>
                  <p>{note.message}</p>
                  <small className="muted"><time dateTime={notification.createdAt}>{formatNotificationTime(notification.createdAt, language)}</time></small>
                  <div className="notification-actions">
                    {(notification.applicationId || notification.target?.kind || notification.target?.providerId) && (
                      <button className="small primary-soft button-with-icon" onClick={() => onVisit?.(notification)}>
                        {visitLabel(notification, isMr)}<ArrowRight size={16} aria-hidden="true" />
                      </button>
                    )}
                    {!notification.read && (
                      <button className="small outline button-with-icon" onClick={() => onMarkRead?.(notification)}>
                        <CheckCheck size={16} aria-hidden="true" />{isMr ? 'वाचले म्हणून चिन्हांकित करा' : 'Mark as read'}
                      </button>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
