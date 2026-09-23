import { languageText, translateNotification } from '../i18n';

const TYPE_ICON = { ACTION_REQUIRED: '!', DOCUMENT_VERIFIED: '✓', APPLICATION_SUBMITTED: '↑' };
const TYPE_CLASS = { ACTION_REQUIRED: 'exception', DOCUMENT_VERIFIED: 'found', APPLICATION_SUBMITTED: 'found' };

function formatWhen(iso, language) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(language === 'mr' ? 'mr-IN' : 'en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

export default function NotificationsPage({ notifications, onSelect, language = 'en' }) {
  const t = languageText(language);
  const items = notifications || [];

  return (
    <main className="container narrow">
      <div className="page-title">
        <div>
          <p className="eyebrow">{t.notificationsNav}</p>
          <h1>{t.notificationsNav}</h1>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="empty-state card">
          <span aria-hidden="true">✓</span>
          <h3>{language === 'en' ? "You're all caught up" : 'आपण सर्व माहिती पाहिली आहे'}</h3>
          <p className="muted">{language === 'en' ? 'Updates about your applications and documents will appear here.' : 'आपल्या अर्ज व दस्तऐवजांबद्दलची नवीन माहिती येथे दिसेल.'}</p>
        </div>
      ) : (
        <div className="notification-list">
          {items.map(notification => {
            const note = translateNotification(notification, language);
            return (
              <button
                key={notification.notificationId}
                className={`card notification-list-item${notification.read ? '' : ' unread'}`}
                onClick={() => onSelect?.(notification)}
              >
                <span className={`requirement-icon requirement-icon-${TYPE_CLASS[notification.type] || 'pending'}`} aria-hidden="true">
                  {TYPE_ICON[notification.type] || '○'}
                </span>
                <span className="notification-list-body">
                  <b>{note.title}</b>
                  <span className="muted">{note.message}</span>
                  <small>{formatWhen(notification.createdAt, language)}</small>
                </span>
                {!notification.read && <span className="notification-list-dot" aria-hidden="true" title={language === 'en' ? 'Unread' : 'न वाचलेले'} />}
              </button>
            );
          })}
        </div>
      )}
    </main>
  );
}
